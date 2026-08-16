import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module.app.config['TESTING'] = True
    app_module.app.config['RATE_LIMIT_ENABLED'] = False
    with app_module.app.test_client() as client:
        yield client