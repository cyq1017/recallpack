def package_for_feature(feature):
    routing = {
        "context_command": "cli",
        "startup_tip": "cli",
        "deployment_command": "cli",
    }
    return routing[feature]
