import socket

import pytest

from cloudlens.webserver import PortInUseError, _check_port_available


def test_check_port_available_passes_for_free_port():
    # Bind to port 0 to let the OS hand back a genuinely free ephemeral port
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("0.0.0.0", 0))
    free_port = probe.getsockname()[1]
    probe.close()

    _check_port_available(free_port)


def test_check_port_available_raises_when_port_taken():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupied.bind(("0.0.0.0", 0))
    occupied.listen(1)
    taken_port = occupied.getsockname()[1]

    try:
        with pytest.raises(PortInUseError):
            _check_port_available(taken_port)
    finally:
        occupied.close()
