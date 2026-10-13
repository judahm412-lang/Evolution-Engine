"""Release numbers do not define scientific checkpoint compatibility."""
CHECKPOINT_FORMAT = 1
SCIENTIFIC_ENGINE = 'fixed-feedforward-2.0'
LEGACY_RELEASES = {'2.0.0'}

def validate_checkpoint(state):
    if state.get('format') != CHECKPOINT_FORMAT:
        raise ValueError('incompatible checkpoint format')
    science = state.get('scientific_engine')
    if science is None:
        if state.get('engine_version') not in LEGACY_RELEASES:
            raise ValueError('incompatible legacy checkpoint version')
    elif science != SCIENTIFIC_ENGINE:
        raise ValueError('incompatible scientific engine')
