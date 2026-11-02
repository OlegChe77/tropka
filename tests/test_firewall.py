"""Разбор правил брандмауэра (вывод netsh): python -m unittest discover tests"""
import unittest

from most.firewall import Status, parse_rules

EXE = r"D:\Программы\Most.exe"

EN_ALLOW = rf"""
Rule Name:                            Мост
----------------------------------------------------------------------
Enabled:                              Yes
Direction:                            In
Profiles:                             Domain,Private
Protocol:                             Any
Program:                              {EXE}
Action:                               Allow
"""

RU_BLOCK_TCP = rf"""
Имя правила:                          мост.exe
----------------------------------------------------------------------
Включен:                              Да
Направление:                          Вход
Profiles:                             Частный
Протокол:                             TCP
Программа:                            {EXE.lower()}
Действие:                             Блокировать
"""

RU_ALLOW_UDP = RU_BLOCK_TCP.replace("TCP", "UDP").replace("Блокировать", "Разрешить")

OTHER = r"""
Rule Name:                            Opera
----------------------------------------------------------------------
Enabled:                              Yes
Profiles:                             Domain,Private,Public
Protocol:                             TCP
Program:                              C:\Opera\opera.exe
Action:                               Allow
"""


class ParseRulesTest(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(parse_rules(OTHER, EXE), "missing")

    def test_allow_english(self):
        self.assertEqual(parse_rules(OTHER + EN_ALLOW, EXE), "allow")

    def test_block_wins_and_russian(self):
        # «Отмена» в окне брандмауэра создаёт блокирующее правило — оно сильнее разрешающего
        self.assertEqual(parse_rules(EN_ALLOW + RU_BLOCK_TCP, EXE), "block")

    def test_udp_only_not_enough(self):
        self.assertEqual(parse_rules(RU_ALLOW_UDP, EXE), "missing")

    def test_public_only_not_enough(self):
        self.assertEqual(parse_rules(EN_ALLOW.replace("Domain,Private", "Public"), EXE), "missing")

    def test_disabled_ignored(self):
        self.assertEqual(parse_rules(EN_ALLOW.replace("Yes", "No"), EXE), "missing")

    def test_crlf(self):
        self.assertEqual(parse_rules(EN_ALLOW.replace("\n", "\r\n"), EXE), "allow")

    def test_status_ok(self):
        self.assertTrue(Status("allow").ok)
        self.assertTrue(Status("unknown").ok)  # не смогли проверить — не пугаем
        self.assertFalse(Status("block").ok)
        self.assertFalse(Status("allow", [{"index": 5, "name": "Сеть"}]).ok)


if __name__ == "__main__":
    unittest.main()
