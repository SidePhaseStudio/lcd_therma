from unittest.mock import Mock, patch

import lcd_therma_stats as lcd


def check():
    response = Mock()
    counts = {"registered": 19, "approved": 18, "not_approved": 1}
    with patch.dict(lcd.os.environ, {"GLOBAL_VECTORS_ADMIN_TOKEN": "test-token"}), \
            patch.object(lcd.requests, "post", return_value=response) as post:
        for expected in (counts, dict.fromkeys(counts, 0)):
            response.json.return_value = {"ok": True, **expected}
            assert lcd.fetch_global_vectors_drivers() == expected
        post.assert_called_with(
            "https://globalvectors.app/api/admin/driver-counts",
            json={"token": "test-token"}, timeout=5,
        )
        for invalid in ({}, {"ok": False, **counts},
                        {"ok": True, **counts, "registered": -1},
                        {"ok": True, **counts, "approved": True},
                        {"ok": True, **counts, "not_approved": "1"}):
            response.json.return_value = invalid
            assert lcd.fetch_global_vectors_drivers() is None
        response.raise_for_status.side_effect = lcd.requests.Timeout("offline")
        assert lcd.fetch_global_vectors_drivers() is None
        post.reset_mock()
        with patch.dict(lcd.os.environ, {"GLOBAL_VECTORS_ADMIN_TOKEN": ""}):
            assert lcd.fetch_global_vectors_drivers() is None
            post.assert_not_called()

    totals = {"players": 0, "in_kbps": 0.0, "out_kbps": 0.0,
              "cpu": 0.1, "mem_mb": 132.3, "worst_loss": 0.0, "partial": False}
    response = Mock()
    with patch.dict(lcd.os.environ, {"GLOBAL_VECTORS_ADMIN_TOKEN": "test-token"}), \
            patch.object(lcd.requests, "post", return_value=response) as post:
        for partial in (False, True):
            expected = {**totals, "partial": partial}
            response.json.return_value = {"ok": True, **expected}
            assert lcd.fetch_global_vectors_server_totals() == expected
        post.assert_called_with(
            "https://globalvectors.app/api/admin/server-totals",
            json={"token": "test-token"}, timeout=5,
        )
        for invalid in ({}, {"ok": False, **totals},
                        {"ok": True, **totals, "mem_mb": None},
                        {"ok": True, **totals, "cpu": "0.1"},
                        {"ok": True, **totals, "players": True},
                        {"ok": True, **totals, "in_kbps": -1},
                        {"ok": True, **totals, "worst_loss": float("nan")},
                        {"ok": True, **totals, "partial": "false"}):
            response.json.return_value = invalid
            assert lcd.fetch_global_vectors_server_totals() is None
        response.raise_for_status.side_effect = lcd.requests.Timeout("offline")
        assert lcd.fetch_global_vectors_server_totals() is None
        post.reset_mock()
        with patch.dict(lcd.os.environ, {"GLOBAL_VECTORS_ADMIN_TOKEN": ""}):
            assert lcd.fetch_global_vectors_server_totals() is None
            post.assert_not_called()

    for serial in ("2025E770099A", "2025E7B071A9"):
        panel = lcd.LyPanel(serial_number=serial)
        device = Mock()
        device.is_kernel_driver_active.return_value = False
        with patch.object(lcd.usb.core, "find", return_value=device) as find, \
                patch.object(lcd.usb.util, "claim_interface"), \
                patch.object(panel, "_recover_endpoints"):
            panel.open()
            find.assert_called_once_with(idVendor=lcd.VID, idProduct=lcd.PID, serial_number=serial)
        with patch.object(panel, "close"), \
                patch.object(lcd.usb.core, "find", return_value=device) as find:
            panel.hard_reset()
            find.assert_called_once_with(idVendor=lcd.VID, idProduct=lcd.PID, serial_number=serial)
            device.reset.assert_called_once()

    original_background = lcd.BACKGROUND.tobytes()
    frame = lcd.render_second_frame({**counts, **totals})
    assert frame.size == (lcd.WIDTH, lcd.HEIGHT)
    for x in (lcd.WIDTH // 3, 2 * lcd.WIDTH // 3):
        assert frame.getpixel((x, 100)) == lcd.LABEL_COLOR
    dimmed_background = lcd.ImageEnhance.Brightness(lcd.BACKGROUND).enhance(0.6)
    for position in ((1500, 200), (1700, 200)):
        assert frame.getpixel(position) == dimmed_background.getpixel(position)
        assert sum(frame.getpixel(position)) < sum(lcd.BACKGROUND.getpixel(position))
    assert lcd.BACKGROUND.tobytes() == original_background
    assert lcd.render_second_frame({}).size == frame.size
    partial_frame = lcd.render_second_frame({**totals, "partial": True})
    assert partial_frame.crop((464, 20, 615, 60)).tobytes() != frame.crop((464, 20, 615, 60)).tobytes()

    with patch.object(lcd, "_stat", wraps=lcd._stat) as stat:
        first_frame = lcd.render_frame({"btc": "BTC_TEST", "bml_total": "999", "vps": {"cpu": "20%"}})
        assert not any(call.args[4] == "Total Users" for call in stat.call_args_list)
        btc_call = next(call for call in stat.call_args_list if call.args[4] == "BTC")
        assert btc_call.args[2] == 2 * lcd.COL_W + 24
        vps_call = next(call for call in stat.call_args_list if call.args[4] == "VPS CPU")
        assert vps_call.args[2] == lcd.COL_W + 24
        assert vps_call.args[5] == "20%"

    with patch.object(lcd, "_stat", wraps=lcd._stat) as stat:
        lcd.render_second_frame({"bml_total": "999", "bml_online": "12"})
        total_call = next(call for call in stat.call_args_list if call.args[4] == "Total Users")
        assert total_call.args[2] == lcd.WIDTH // 3 + 24
        assert total_call.args[5] == "999"
        online_call = next(call for call in stat.call_args_list if call.args[4] == "Online")
        assert online_call.args[5] == "12"


if __name__ == "__main__":
    check()
    print("Second-panel checks passed")
