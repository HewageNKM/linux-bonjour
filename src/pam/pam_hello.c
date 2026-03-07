#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <sys/time.h>

#define SOCKET_PATH "/run/linux-hello.sock"

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    int sock = 0;
    struct sockaddr_un serv_addr;
    char buffer[128] = {0};
    const char *user;
    struct timeval tv;

    // 1. Get username
    if (pam_get_user(pamh, &user, NULL) != PAM_SUCCESS || user == NULL) {
        return PAM_AUTH_ERR;
    }

    if ((sock = socket(AF_UNIX, SOCK_STREAM, 0)) < 0) {
        return PAM_AUTH_ERR;
    }

    // Set timeout (2 seconds)
    tv.tv_sec = 2;
    tv.tv_usec = 0;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof tv);

    serv_addr.sun_family = AF_UNIX;
    strncpy(serv_addr.sun_path, SOCKET_PATH, sizeof(serv_addr.sun_path) - 1);

    if (connect(sock, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        close(sock);
        return PAM_AUTH_ERR;
    }

    // 3. Send the "AUTH <username>" command
    snprintf(buffer, sizeof(buffer), "AUTH %s", user);
    send(sock, buffer, strlen(buffer), 0);

    // 4. Wait for the response
    memset(buffer, 0, sizeof(buffer));
    if (read(sock, buffer, sizeof(buffer) - 1) <= 0) {
        close(sock);
        return PAM_AUTH_ERR;
    }
    
    close(sock);

    if (strcmp(buffer, "SUCCESS") == 0) {
        pam_info(pamh, "Windows Hello: Face Recognized.");
        return PAM_SUCCESS;
    }

    return PAM_AUTH_ERR;
}

PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    return PAM_SUCCESS;
}