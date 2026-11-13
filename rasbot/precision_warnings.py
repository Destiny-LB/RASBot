"""Fixed warning policy: informational metadata never excuses lost evidence."""
def classify(log):
    result = []
    for line in log.splitlines():
        if 'WARNING:' not in line:
            continue
        message = line.split('WARNING:', 1)[1].strip()
        if message == "library.source_path should be 'docs/trigger_library.md'":
            code, blocking = 'reference_label', False
        elif 'duplicate case signature' in message:
            code, blocking = 'duplicate_input', True
        elif 'primary trigger' in message or 'stale' in message or 'coverage' in message or 'TRIGGER-' in message:
            code, blocking = 'coverage_consistency', True
        elif 'runnable' in message or 'canonical' in message or 'sha256' in message:
            code, blocking = 'reference_integrity', True
        else:
            code, blocking = 'unclassified', True
        result.append({'code': code, 'blocking': blocking, 'message': message[:1000]})
    return result
