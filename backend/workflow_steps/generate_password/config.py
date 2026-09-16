def get_config() -> dict:
    return {
        "length": 16,
        "min_digits": 2,
        "min_uppercase": 2,
        "min_lowercase": 2,
        "min_special": 2,
        "destination_path": "generated_password.value",
    }
