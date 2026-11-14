from unittest.mock import Mock, patch

import lcd_therma_stats as lcd


def check():
    response = Mock()
    with patch.object(lcd, "BREVO_API_KEY", "test-key"), \
            patch.object(lcd.requests, "get", return_value=response) as request:
        for remaining, sent in ((300, 0), (295, 5), (0, 300)):
            response.json.return_value = {"plan": [
                {"type": "sms", "creditsType": "sendLimit", "credits": 10},
                {"type": "free", "creditsType": "sendLimit", "credits": remaining},
            ]}
            assert lcd.fetch_brevo_sent_today() == sent
        request.assert_called_with("https://api.brevo.com/v3/account",
                                   headers={"api-key": "test-key"}, timeout=5)
        for remaining in (-1, 301, True, "295", None):
            response.json.return_value = {"plan": [
                {"type": "free", "creditsType": "sendLimit", "credits": remaining},
            ]}
            assert lcd.fetch_brevo_sent_today() is None
        for data in ({}, {"plan": []}, {"plan": [{"type": "paid", "creditsType": "sendLimit", "credits": 295}]}):
            response.json.return_value = data
            assert lcd.fetch_brevo_sent_today() is None
        response.raise_for_status.side_effect = lcd.requests.Timeout("offline")
        assert lcd.fetch_brevo_sent_today() is None
        request.reset_mock()
        with patch.object(lcd, "BREVO_API_KEY", ""):
            assert lcd.fetch_brevo_sent_today() is None
            request.assert_not_called()

    with patch.object(lcd, "_stat", wraps=lcd._stat) as stat:
        lcd.render_second_frame({"brevo_sent": "5/300"})
        call = next(call for call in stat.call_args_list if call.args[4] == "Emails sent today")
        assert call.args[2:4] == (2 * lcd.WIDTH // 3 + 24, 28)
        assert call.args[5] == "5/300"
    with patch.object(lcd, "_stat", wraps=lcd._stat) as stat:
        lcd.render_frame({"brevo_sent": "5/300"})
        assert not any(call.args[4] == "Emails sent today" for call in stat.call_args_list)


if __name__ == "__main__":
    check()
    print("Brevo checks passed")
