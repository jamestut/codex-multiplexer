package main

import "golang.org/x/sys/unix"

func peerPID(fd int) (int, error) {
	// LOCAL_PEERPID identifies the process on the other end of the Unix socket.
	return unix.GetsockoptInt(fd, unix.SOL_LOCAL, unix.LOCAL_PEERPID)
}
