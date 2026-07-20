def backend_for_example(example_kind):
    routing = {
        "new_example": "kuzu",
        "legacy_compatibility": "kuzu",
    }
    return routing[example_kind]
