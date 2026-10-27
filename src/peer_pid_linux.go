package main

import "golang.org/x/sys/unix"

func peerPID(fd int) (int, error) {
	// SO_PEERCRED identifies the process that created the listening socket.
	credentials, err := unix.GetsockoptUcred(fd, unix.SOL_SOCKET, unix.SO_PEERCRED)
	if err != nil {
		return 0, err
	}
	return int(credentials.Pid), nil
}
