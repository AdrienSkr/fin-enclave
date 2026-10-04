import pytest

from fin_enclave.ingestion.ibm_aml import parse_ibm_patterns, select_attempts

MOCK_PATTERNS = """
BEGIN LAUNDERING ATTEMPT - FAN-OUT: Max 3-degree Fan-Out
2022/09/01 00:06,021174,ACC001,012,ACC002,2848.96,Euro,2848.96,Euro,ACH,1
2022/09/01 04:33,021174,ACC001,020,ACC003,8630.40,Euro,8630.40,Euro,ACH,1
2022/09/01 09:14,021174,ACC001,020,ACC004,3564.00,Euro,3564.00,Euro,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT

BEGIN LAUNDERING ATTEMPT - CYCLE: Max 3 hops
2022/09/01 01:00,010,ACC010,020,ACC020,15000.00,US Dollar,15000.00,US Dollar,ACH,1
2022/09/02 02:00,020,ACC020,030,ACC030,14750.00,US Dollar,14750.00,US Dollar,ACH,1
2022/09/03 03:00,030,ACC030,010,ACC010,14500.00,US Dollar,14500.00,US Dollar,ACH,1
END LAUNDERING ATTEMPT - CYCLE

BEGIN LAUNDERING ATTEMPT - RANDOM: Unsupported currency
2022/09/01 01:00,010,ACC010,020,ACC020,15000.00,Yuan,15000.00,Yuan,ACH,1
END LAUNDERING ATTEMPT - RANDOM
"""


def test_parse_ibm_patterns():
    attempts = parse_ibm_patterns(MOCK_PATTERNS)
    assert len(attempts) == 3

    fan_out = attempts[0]
    assert fan_out["typology"] == "FAN-OUT"
    assert len(fan_out["transactions"]) == 3
    assert fan_out["transactions"][0]["from_account"] == "ACC001"
    assert fan_out["transactions"][0]["to_account"] == "ACC002"
    assert fan_out["transactions"][0]["amount"] == 2848.96
    assert fan_out["transactions"][0]["currency"] == "EUR"
    assert fan_out["transactions"][0]["date"] == "2022-09-01"

    cycle = attempts[1]
    assert cycle["typology"] == "CYCLE"
    assert len(cycle["transactions"]) == 3
    assert cycle["transactions"][0]["currency"] == "USD"


def test_select_attempts():
    attempts = parse_ibm_patterns(MOCK_PATTERNS)
    selected = select_attempts(attempts, seed=42, typologies=["CYCLE", "FAN-OUT"])
    assert len(selected) == 2
    typos = [s["typology"] for s in selected]
    assert typos == ["CYCLE", "FAN-OUT"]

    # Tentative avec typologie absente doit lever ValueError
    with pytest.raises(ValueError, match="Aucune tentative trouvée pour la typologie 'BIPARTITE'"):
        select_attempts(attempts, seed=42, typologies=["BIPARTITE"])
