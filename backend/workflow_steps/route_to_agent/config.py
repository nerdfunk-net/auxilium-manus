def get_config() -> dict:
    return {
        # Agent source configured under Settings -> Sources -> Agents.
        "agent_source_id": "",
        # Name of the handler the agent runs; the app never sends code.
        "handler": "",
        # Static JSON object handed to the handler next to the per-device inputs.
        "params": {},
        # Attribute paths (bags, parsed.*, device.*) whose values are sent.
        "input_paths": [],
        # Device content sent as text: running_config, startup_config, latest_command_output,
        # or command_output:<node_id>.
        "content_inputs": [],
        # Where the agent's answer is written (bag.field); the answer is a JSON object.
        "destination_path": "",
        # The only keys the agent may return; anything else fails the device.
        "output_keys": [],
        "allow_missing_outputs": False,
        "timeout_seconds": 30,
    }
