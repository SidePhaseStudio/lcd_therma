from unittest.mock import patch

import lcd_therma_stats as lcd


def check():
    with patch.multiple(lcd, PERSON1_IP="s21", PERSON1_IP_ALT="s20",
                        PERSON1_DEVICE="S21", PERSON1_DEVICE_ALT="S20"):
        for replies, expected in [([False, False], ""), ([True, False], "S21"),
                                  ([False, True], "S20"), ([True, True], "S21 + S20")]:
            with patch.object(lcd, "fetch_ip_reachable", side_effect=replies) as ping:
                assert lcd.fetch_person1_reachable() == expected
                assert ping.call_count == 2
        with patch.object(lcd, "PERSON1_IP", ""):
            assert lcd.fetch_person1_reachable() is None


if __name__ == "__main__":
    check()
    print("Presence checks passed")
