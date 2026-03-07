#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>

/* The path must match your Python Daemon's SOCKET_PATH */
#define SOCKET_PATH "/run/linux-hello.sock"

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    int sock = 0;
    struct sockaddr_un serv_addr;
    char buffer[10] = {0};

    // 1. Create a socket (Like initializing a 'fetch' request)
    if ((sock = socket(AF_UNIX, SOCK_STREAM, 0)) < 0) {
        return PAM_AUTH_ERR;
    }

    serv_addr.sun_family = AF_UNIX;
    strncpy(serv_addr.sun_path, SOCKET_PATH, sizeof(serv_addr.sun_path) - 1);

    // 2. Connect to our Python Daemon
    if (connect(sock, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        // If the daemon isn't running, we fail silently so user can type password
        close(sock);
        return PAM_AUTH_ERR;
    }

    // 3. Send the "AUTH" command
    send(sock, "AUTH", 4, 0);

    // 4. Wait for the response ("SUCCESS" or "FAILURE")
    read(sock, buffer, 10);
    close(sock);

    if (strcmp(buffer, "SUCCESS") == 0) {
        // Optional: Print a message to the terminal like a "Welcome" toast
        pam_info(pamh, "Windows Hello: Face Recognized.");
        return PAM_SUCCESS;
    }

    return PAM_AUTH_ERR;
}

/* These are boilerplate functions required by PAM even if empty */
PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    return PAM_SUCCESS;
}