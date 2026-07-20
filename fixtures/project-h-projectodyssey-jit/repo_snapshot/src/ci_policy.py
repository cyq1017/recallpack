def handle_jit_crash(error_message):
    return {
        "action": "inspect",
        "retry": False,
        "retry_attempts": 0,
        "continue_on_error": False,
        "skip": False,
        "minimal_reproducer_required": False,
    }
