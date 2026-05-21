$ErrorActionPreference = "Stop"

python -m py_compile handlers.py visit_card.py visit_flows.py
python -m pytest tests/test_join_entry_screens.py tests/test_client_visit_registration_flow.py tests/test_fsm_debug.py -q

Write-Host "Registration smoke (MAX) passed."
