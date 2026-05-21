$ErrorActionPreference = "Stop"

python -m py_compile funnel_db.py visit_flows.py
python -m pytest tests/test_admin_menu_parity.py tests/test_client_visit_registration_flow.py -q

Write-Host "ERP smoke (MAX) passed."
