from forward_nautobot.integrations.forward.adapters import ForwardSourceAdapter


def test_source_adapter_keeps_raw_rows_by_identity():
    adapter = ForwardSourceAdapter(model_names=("devices",))
    rows = [
        {
            "name": "device-1",
            "location": "Site A",
            "vendor": "Example Manufacturer",
            "model": "MODEL-A",
            "platform": "EXAMPLE_OS",
        }
    ]

    loaded = adapter.load_rows("devices", rows)

    assert adapter.count("devices") == 1
    assert loaded[0].record_key == "device-1"
    assert loaded[0].fields == rows[0]
    assert adapter.records["devices"]["device-1"].fields == rows[0]
    assert adapter.get_all("devices")[0].dict()["name"] == "device-1"
