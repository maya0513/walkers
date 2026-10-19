"""Keep optional editor socket limitations separate from project errors."""

def classify_errors(output, allow_editor_socket_errors=False):
    errors, limitations = [], []
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if not (line.startswith("ERROR:") or "SCRIPT ERROR" in line):
            continue
        context = "\n".join(lines[i:i+3])
        socket_error = (
            line == 'ERROR: Condition "_sock == -1" is true. Returning: FAILED'
            and 'at: _inet_open (drivers/unix/net_socket_unix.cpp:' in context
        ) or (
            line == 'ERROR: Condition "err != OK" is true. Returning: ERR_CANT_CREATE'
            and 'at: listen (core/io/tcp_server.cpp:' in context
        )
        if allow_editor_socket_errors and socket_error:
            limitations.append(line)
        else:
            errors.append(line)
    return errors, limitations
