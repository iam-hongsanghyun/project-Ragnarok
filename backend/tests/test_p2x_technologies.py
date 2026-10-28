"""The P2X technology data file: provenance on every value, overrides, and the annualisation identity."""
from __future__ import annotations

import json

import pytest
from numpy.testing import assert_allclose

from backend.app.p2x import technologies as tech
from backend.pypsa.utils.annuity import annuity_factor

VERIFIED = {"file", "derived", "literature-recalled", "assumption"}


def test_every_parameter_carries_value_unit_source_and_flags() -> None:
    data = tech.load_technologies()
    assert data["sources"]["technology-data"]["version"] == "v0.15.0"
    assert len(data["sources"]["technology-data"]["commit"]) == 40
    assert data["basis"]["currency"] == "EUR" and data["basis"]["costYear"] == 2025
    for tkey, body in data["technologies"].items():
        assert body["parameters"], tkey
        for name, p in body["parameters"].items():
            where = f"{tkey}.{name}"
            assert isinstance(p["value"], (int, float)), where
            assert p["unit"], where
            assert p["source"]["document"] and p["source"]["locator"] and p["source"]["year"], where
            assert p["verified"] in VERIFIED, where
            if p["unit"].startswith("EUR"):                    # money values state their cost year and currency
                assert p["costYear"] == 2025 and p["currency"] == "EUR", where


def test_required_technologies_are_covered() -> None:
    techs = set(tech.load_technologies()["technologies"])
    assert {"electrolyser_aec", "electrolyser_pem", "h2_compressor", "h2_storage_tank", "h2_storage_cavern", "asu", "haber_bosch",
            "methanolisation", "fischer_tropsch", "co2_dac", "co2_point", "water", "nh3_storage", "meoh_storage", "efuel_storage"} <= techs


def test_constants_follow_the_specification() -> None:
    k = tech.constants()
    assert k["h2_lhv_kwh_per_kg"] == 33.33 and k["nh3_lhv_kwh_per_kg"] == 5.17 and k["meoh_lhv_kwh_per_kg"] == 5.54


def test_electrolyser_values_are_the_dea_2030_100mw_sheet() -> None:
    d = tech.parameter_defaults()
    assert_allclose(d["electrolyser_aec"]["specific_energy"], 53.5658, atol=5e-5)      # kWh_el/kg_H2, stack + BOP
    assert_allclose(d["electrolyser_aec"]["capex"], 550 * 1.2573346, rtol=1e-6)         # EUR2020 550 -> EUR2025
    assert d["electrolyser_aec"]["stack_lifetime_hours"] == 92500 and d["electrolyser_pem"]["stack_lifetime_hours"] == 77500
    assert_allclose(tech.lhv_efficiency(d["electrolyser_aec"]["specific_energy"], 33.33), 0.6222, atol=5e-5)


def test_overrides_and_validation() -> None:
    eff = tech.resolve_parameters({"electrolyser_aec.capex": 600})
    assert eff["electrolyser_aec"]["capex"] == 600 and eff["electrolyser_pem"]["capex"] == tech.parameter_defaults()["electrolyser_pem"]["capex"]
    with pytest.raises(ValueError, match="Unknown P2X parameter"):
        tech.resolve_parameters({"electrolyser_aec.nope": 1})
    with pytest.raises(ValueError, match="number"):
        tech.resolve_parameters({"electrolyser_aec.capex": "x"})
    cat = tech.catalogue({"electrolyser_aec.capex": 600})
    p = cat["technologies"]["electrolyser_aec"]["parameters"]["capex"]
    assert p["value"] == 600 and p["default"] == pytest.approx(691.534, rel=1e-6)


def test_external_data_file_is_honoured(tmp_path, monkeypatch) -> None:
    data = json.loads(tech.BUNDLED_FILE.read_text(encoding="utf-8"))
    data["technologies"]["electrolyser_aec"]["parameters"]["capex"]["value"] = 111.0
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(tech.ENV_FILE, str(path))
    assert tech.parameter_defaults()["electrolyser_aec"]["capex"] == 111.0


@pytest.mark.parametrize("fom,life,rate", [(4.0, 25, 0.05), (2.0, 20, 0.07), (0.0, 30, 0.03)])
def test_overnight_equivalent_annualises_to_capex_times_annuity_plus_fom(fom, life, rate) -> None:
    k = 1.0e6
    k_eq = tech.overnight_equivalent(k, fom, life, rate)
    assert_allclose(k_eq * annuity_factor(rate, life), k * (annuity_factor(rate, life) + fom / 100), rtol=1e-12)
    a = annuity_factor(rate, life)
    assert_allclose(tech.fom_share(fom, life, rate), (fom / 100) / (a + fom / 100), rtol=1e-12)


def test_unit_conversions() -> None:
    assert_allclose(tech.kg_to_mwh(1000.0, 33.33), 33.33, rtol=1e-12)
    assert_allclose(tech.mwh_to_kg(33.33, 33.33), 1000.0, rtol=1e-12)
