"""Проверка сервера: python -m unittest discover tests"""
import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from most.certs import ensure_cert, server_context
from most.events import Events
from most.server import Bridge, safe_name
from most.store import Store


class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir / "t.db")
        self.events = Events()
        self.log = []
        self.events.subscribe(lambda kind, data: self.log.append((kind, data)))
        self.inbox = self.dir / "in"
        self.bridge = Bridge(self.store, self.inbox, self.events, pc_name="Тест-ПК")
        self.client = TestClient(TestServer(self.bridge.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.store.close()
        self.tmp.cleanup()

    async def login(self):
        r = await self.client.post("/api/login", json={"pin": self.bridge.pin})
        self.assertEqual(r.status, 200)

    async def put(self, name, body):
        return await self.client.put("/api/upload", data=body,
                                     headers={"X-File-Name": quote(name)})

    async def test_needs_pin(self):
        self.assertEqual((await self.client.get("/api/me")).status, 401)
        self.assertEqual((await self.put("a.txt", b"x")).status, 401)
        self.assertEqual(list(self.inbox.iterdir()), [])
        self.assertEqual((await self.client.get("/")).status, 200)  # страница входа открыта

    async def test_wrong_pin_locks(self):
        wrong = "000000" if self.bridge.pin != "000000" else "111111"
        for _ in range(5):
            r = await self.client.post("/api/login", json={"pin": wrong})
            self.assertEqual(r.status, 403)
        r = await self.client.post("/api/login", json={"pin": self.bridge.pin})
        self.assertEqual(r.status, 429)

    async def test_login_and_me(self):
        await self.login()
        r = await self.client.get("/api/me")
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["pc"], "Тест-ПК")
        self.assertEqual(self.log[0][0], "device_joined")

    async def test_qr_link(self):
        r = await self.client.get(f"/?k={self.bridge.pin}", allow_redirects=False)
        self.assertEqual(r.status, 302)
        self.assertEqual(r.headers["Location"], "/")
        self.assertEqual((await self.client.get("/api/me")).status, 200)

    async def test_upload(self):
        await self.login()
        body = os.urandom(3 * 1024 * 1024 + 7)
        r = await self.put("Фото отпуска.jpg", body)
        self.assertEqual(r.status, 200, await r.text())
        saved = self.inbox / "Фото отпуска.jpg"
        self.assertEqual(hashlib.sha256(saved.read_bytes()).digest(), hashlib.sha256(body).digest())
        kinds = [k for k, _ in self.log]
        self.assertIn("upload_started", kinds)
        self.assertIn("file_received", kinds)
        hist = self.store.history()
        self.assertEqual((hist[-1]["name"], hist[-1]["size"]), ("Фото отпуска.jpg", len(body)))
        self.assertEqual([p for p in self.inbox.iterdir() if p.suffix == ".part"], [])

    async def test_same_name_and_bad_names(self):
        await self.login()
        for _ in range(3):
            self.assertEqual((await self.put("a.txt", b"1")).status, 200)
        self.assertEqual((await self.put("../../evil.txt", b"2")).status, 200)
        self.assertEqual((await self.put("CON.txt", b"3")).status, 200)
        names = sorted(p.name for p in self.inbox.iterdir())
        self.assertEqual(names, ["_CON.txt", "a (1).txt", "a (2).txt", "a.txt", "evil.txt"])
        self.assertFalse((self.dir / "evil.txt").exists())

    async def second_phone(self):
        """Второй телефон со своими cookie."""
        s = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        self.addAsyncCleanup(s.close)
        r = await s.post(self.client.make_url("/api/login"), json={"pin": self.bridge.pin})
        self.assertEqual(r.status, 200)
        return s

    def device_ids(self):
        return [d["id"] for k, d in self.log if k == "device_joined"]

    async def feed(self, session=None):
        s = session or self.client
        url = self.client.make_url("/api/feed") if session else "/api/feed"
        r = await s.get(url)
        self.assertEqual(r.status, 200)
        return {it["id"]: it for it in (await r.json())["items"]}

    async def test_offer_and_download(self):
        await self.login()
        dev = self.device_ids()[0]
        body = os.urandom(200_000)
        f = self.dir / "отчёт.pdf"
        f.write_bytes(body)
        hid = self.bridge.offer_file(f)
        item = (await self.feed())[hid]
        self.assertEqual((item["who"], item["delivered"], item["available"]), ("pc", False, True))
        self.assertNotIn("path", item)
        self.assertEqual(len(self.store.pending_for(dev)), 1)

        r = await self.client.get(f"/api/file/{hid}")
        self.assertEqual(r.status, 200)
        self.assertEqual(await r.read(), body)
        self.assertIn("filename*=UTF-8''%D0%BE%D1%82", r.headers["Content-Disposition"])
        self.assertEqual(self.store.pending_for(dev), [])
        self.assertTrue((await self.feed())[hid]["delivered"])
        self.assertIn("delivered", [k for k, _ in self.log])

    async def test_offer_to_one_phone(self):
        await self.login()
        other = await self.second_phone()
        a = self.device_ids()[0]
        f = self.dir / "a.txt"
        f.write_text("x")
        hid = self.bridge.offer_file(f, device_id=a)
        self.assertNotIn(hid, await self.feed(other))
        r = await other.get(self.client.make_url(f"/api/file/{hid}"))
        self.assertEqual(r.status, 404)
        self.assertEqual((await self.client.get(f"/api/file/{hid}")).status, 200)

    async def test_shared_feed(self):
        await self.login()
        other = await self.second_phone()
        r = await self.put("с телефона А.txt", b"abc")
        fid = (await r.json())["id"]
        r = await self.client.post("/api/text", json={"text": "привет https://example.com"})
        tid = (await r.json())["id"]
        mine, theirs = await self.feed(), await self.feed(other)
        self.assertEqual((mine[fid]["who"], mine[tid]["who"]), ("me", "me"))
        self.assertEqual((theirs[fid]["who"], theirs[tid]["who"]), ("other", "other"))
        self.assertEqual(theirs[tid]["text"], "привет https://example.com")
        r = await other.get(self.client.make_url(f"/api/file/{fid}"))
        self.assertEqual(await r.read(), b"abc")
        self.assertIn("text_received", [k for k, _ in self.log])
        self.assertEqual((await self.client.post("/api/text", json={"text": "  "})).status, 400)

    async def test_live_events(self):
        await self.login()
        other = await self.second_phone()
        r = await other.get(self.client.make_url("/api/events"))
        self.assertEqual(r.status, 200)

        async def next_item():
            while True:
                line = await asyncio.wait_for(r.content.readline(), 3)
                if line.startswith(b"data: "):
                    return json.loads(line[6:])["item"]

        await asyncio.wait_for(r.content.readline(), 3)  # retry:
        self.assertIn("device_online", [k for k, _ in self.log])
        await self.client.post("/api/text", json={"text": "с телефона"})
        self.assertEqual((await next_item())["text"], "с телефона")
        await asyncio.to_thread(self.bridge.offer_text, "с ПК из другого потока")
        item = await next_item()
        self.assertEqual((item["text"], item["who"]), ("с ПК из другого потока", "pc"))
        r.close()

    async def test_download_progress(self):
        await self.login()
        ev = await self.client.get("/api/events")
        await asyncio.wait_for(ev.content.readline(), 3)  # retry:
        f = self.dir / "фото.jpg"
        f.write_bytes(os.urandom(600_000))
        hid = self.bridge.offer_file(f)

        async def next_msg():
            while True:
                line = await asyncio.wait_for(ev.content.readline(), 3)
                if line.startswith(b"data: "):
                    return json.loads(line[6:])

        self.assertEqual((await next_msg())["type"], "item")
        self.assertTrue((await self.feed())[hid]["view"])
        r = await self.client.get(f"/api/file/{hid}")
        await r.read()
        states = []
        while not states or states[-1] not in ("done", "error"):
            msg = await next_msg()
            self.assertEqual((msg["type"], msg["id"]), ("dl", hid))
            states.append(msg["state"])
        self.assertEqual((states[0], states[-1]), ("start", "done"))

        f.unlink()
        self.assertEqual((await self.client.get(f"/api/file/{hid}")).status, 410)
        msg = await next_msg()
        self.assertEqual((msg["state"], msg["error"]), ("error", "Файла больше нет на компьютере"))
        ev.close()

    async def test_view(self):
        await self.login()
        pic = self.dir / "a.png"
        pic.write_bytes(b"\x89PNG....")
        page = self.dir / "a.html"
        page.write_text("<script>alert(1)</script>")
        r = await self.client.get(f"/api/file/{self.bridge.offer_file(pic)}?view=1")
        self.assertEqual((r.status, r.headers["Content-Type"]), (200, "image/png"))
        self.assertIn("sandbox", r.headers["Content-Security-Policy"])
        self.assertEqual(await r.read(), b"\x89PNG....")
        hid = self.bridge.offer_file(page)
        self.assertFalse((await self.feed())[hid]["view"])
        self.assertEqual((await self.client.get(f"/api/file/{hid}?view=1")).status, 415)
        self.assertFalse((await self.feed())[hid]["delivered"])  # просмотр — не скачивание

    async def test_page_links(self):
        # папку из браузера не открыть — только подсказка; «Помощь проекту» — обычная ссылка
        r = await self.client.get("/")
        self.assertIn('href="https://dalink.to/olegche"', await r.text())
        js = await (await self.client.get("/static/app.js")).text()
        self.assertNotIn("intent:", js)
        self.assertIn("«Файлы» → «Загрузки»", js)

    async def test_clear_feed(self):
        await self.login()
        ev = await self.client.get("/api/events")
        await asyncio.wait_for(ev.content.readline(), 3)  # retry:
        f = self.dir / "a.txt"
        f.write_text("файл")
        old = self.bridge.offer_file(f)
        self.bridge.offer_text("привет")
        await (await self.client.get(f"/api/file/{old}")).read()
        self.assertEqual((await self.client.post("/api/clear")).status, 200)
        self.assertEqual(await self.feed(), {})
        self.assertTrue(f.is_file())  # файлы не трогаем
        cleared = [d for k, d in self.log if k == "feed_cleared"]
        self.assertTrue(cleared and cleared[0]["device"])  # кто очистил — имя телефона
        msgs = []
        while not msgs or msgs[-1]["type"] != "clear":
            line = await asyncio.wait_for(ev.content.readline(), 3)
            if line.startswith(b"data: "):
                msgs.append(json.loads(line[6:]))
        ev.close()
        # id после очистки не начинаются заново: старое «скачано» не прилипает к новому
        new = self.bridge.offer_file(f)
        self.assertGreater(new, old)
        self.assertFalse((await self.feed())[new]["delivered"])
        self.store.close()
        self.store = Store(self.dir / "t.db")  # и после перезапуска
        self.bridge.store = self.store
        self.store.clear_history()
        self.assertGreater(self.store.add_history("out", "text", None, text="x"), new)

    async def test_missing_file(self):
        await self.login()
        f = self.dir / "b.txt"
        f.write_text("x")
        hid = self.bridge.offer_file(f)
        f.unlink()
        self.assertFalse((await self.feed())[hid]["available"])
        self.assertEqual((await self.client.get(f"/api/file/{hid}")).status, 410)

    async def test_empty_file(self):
        await self.login()
        self.assertEqual((await self.put("пусто.txt", b"")).status, 200)
        self.assertEqual((self.inbox / "пусто.txt").stat().st_size, 0)


class HttpsTest(unittest.IsolatedAsyncioTestCase):
    async def test_https_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            ctx = server_context(*ensure_cert(d, ["127.0.0.1"]))
            store = Store(d / "t.db")
            bridge = Bridge(store, d / "in", host="127.0.0.1", port=0, ssl_context=ctx)
            await bridge.start()
            try:
                jar = aiohttp.CookieJar(unsafe=True)
                async with aiohttp.ClientSession(cookie_jar=jar) as s:
                    url = bridge.pair_url("127.0.0.1")
                    async with s.get(url, ssl=False) as r:  # вход по QR-ссылке
                        self.assertEqual(r.status, 200)
                    async with s.put(bridge.url("127.0.0.1") + "api/upload", data=b"hello",
                                     headers={"X-File-Name": "h.txt"}, ssl=False) as r:
                        self.assertEqual(r.status, 200)
                self.assertEqual((d / "in" / "h.txt").read_bytes(), b"hello")
            finally:
                await bridge.stop()
                store.close()


class NamesTest(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(safe_name('a<b>:c?.txt'), "a_b__c_.txt")
        self.assertEqual(safe_name("  .. "), "файл")
        self.assertEqual(safe_name("nul"), "_nul")
        self.assertEqual(len(safe_name("я" * 300 + ".jpg")), 180)


if __name__ == "__main__":
    unittest.main()
