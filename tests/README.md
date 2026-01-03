# UNAS Pro Integration Tests

Comprehensive unit tests for the UNAS Pro Home Assistant integration.

## Test Coverage

### Critical Components Tested

1. **SSH Manager** (`test_ssh_manager.py`)
   - MQTT credential validation after deployment
   - Script installation checks
   - Service status monitoring
   - Connection management

2. **Fan Mode Persistence** (`test_select.py`)
   - Migration from `/tmp/fan_mode` to `/root/fan_mode`
   - MQTT as source of truth
   - Default mode behavior
   - Service start/stop logic
   - Mode change handling

3. **Sensor Discovery** (`test_sensor.py`)
   - Drive discovery with retry logic
   - Pool discovery
   - No duplicate sensors
   - Empty MQTT data handling

4. **MQTT Client** (`test_mqtt_client.py`)
   - Message parsing (numbers, floats, strings)
   - Topic filtering
   - Fan curve parameter handling
   - Data retrieval

5. **Coordinator** (`test_coordinator.py`)
   - Firmware update detection
   - Automatic script reinstallation
   - Service status checks
   - MQTT integration validation
   - Error handling

## Running Tests

### Install Dependencies

```bash
# Using uv (recommended)
uv pip install pytest pytest-asyncio pytest-cov

# Or using pip
pip install pytest pytest-asyncio pytest-cov
```

### Run All Tests

```bash
# From project root
pytest

# With verbose output
pytest -v

# With coverage report
pytest --cov=custom_components.unas_pro --cov-report=html
```

### Run Specific Test Files

```bash
# Test only SSH manager
pytest tests/test_ssh_manager.py

# Test only fan mode persistence
pytest tests/test_select.py

# Test only coordinator
pytest tests/test_coordinator.py
```

### Run Specific Tests

```bash
# Run a specific test function
pytest tests/test_select.py::test_fan_mode_migration_from_tmp

# Run tests matching a pattern
pytest -k "persistence"
```

## Test Structure

Each test file follows this pattern:

```python
# Fixtures from conftest.py
- mock_ssh_connection
- mock_asyncssh
- mock_mqtt
- mock_coordinator
- hass_instance

# Test functions
@pytest.mark.asyncio  # For async tests
async def test_something():
    # Arrange
    # Act
    # Assert
```

## Coverage Report

After running tests with coverage:

```bash
# View terminal report
pytest --cov=custom_components.unas_pro --cov-report=term-missing

# Generate HTML report
pytest --cov=custom_components.unas_pro --cov-report=html

# Open HTML report
open htmlcov/index.html
```

## Key Test Scenarios

### Bug Fixes Covered

1. **MQTT Credential Validation** (Fix from bug review)
   - Validates credentials were replaced correctly
   - Handles matching default credentials
   - Catches failed replacements

2. **Fan Mode Persistence** (Fix from persistence bug)
   - Tests migration from volatile to persistent storage
   - Verifies MQTT is source of truth
   - Tests default mode on fresh install
   - Verifies service management on mode changes

3. **Drive Discovery Retry** (Fix from bug review)
   - Tests retry logic for delayed MQTT data
   - Prevents duplicate sensors
   - Handles empty data gracefully

4. **Firmware Update Detection** (Core feature)
   - Detects missing scripts
   - Automatically reinstalls
   - Checks service status

## Adding New Tests

When adding features, add corresponding tests:

```python
@pytest.mark.asyncio
async def test_new_feature(mock_coordinator):
    """Test description."""
    # Setup
    mock_coordinator.some_method = AsyncMock(return_value="value")
    
    # Execute
    result = await some_function(mock_coordinator)
    
    # Verify
    assert result == expected_value
    mock_coordinator.some_method.assert_called_once()
```

## Continuous Integration

These tests can be run in CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run tests
  run: |
    pip install pytest pytest-asyncio pytest-cov
    pytest --cov=custom_components.unas_pro
```

## Test Philosophy

- **Unit tests**: Test individual components in isolation
- **Mock external dependencies**: SSH, MQTT, Home Assistant core
- **Test bug fixes**: Every bug fix should have a test
- **Test edge cases**: Empty data, errors, timeouts
- **Clear test names**: Describe what is being tested
