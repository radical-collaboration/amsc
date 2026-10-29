/* taskrun -- minimal benchmark payload for the rhapsody scaling tests.
 *
 * Records where and when it ran (host, the logical CPUs the backend gave it,
 * wall-clock start/end) and, for non-zero durations, busy-occupies its
 * allocated cores so resource-utilization measurements see real load.
 *
 *   usage:  taskrun <duration_sec> <n_cores> <uid> <out_dir>
 *   writes: <out_dir>/<uid>.json   -- one JSON object, newline terminated
 *
 * build:  cc -O2 -pthread -o taskrun taskrun.c
 */
#define _GNU_SOURCE
#include <sched.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static double now_wall(void) { struct timespec t; clock_gettime(CLOCK_REALTIME,  &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static double now_mono(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

static double g_deadline;  /* monotonic time to spin until */

static void *spin(void *arg) {
    (void) arg;
    volatile double x = 0;
    while (now_mono() < g_deadline)
        for (int i = 0; i < 10000; i++) x += i;
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr, "usage: %s dur ncores uid outdir\n", argv[0]); return 2; }
    double      dur    = atof(argv[1]);
    int         ncores = atoi(argv[2]);
    const char *uid    = argv[3];
    const char *outdir = argv[4];

    char host[256] = {0};
    gethostname(host, sizeof host);

    /* the affinity mask the backend handed us = the logical CPUs we may use */
    char cpus[4096] = {0};
    cpu_set_t set;
    CPU_ZERO(&set);
    if (sched_getaffinity(0, sizeof set, &set) == 0) {
        int first = 1;
        for (int c = 0; c < CPU_SETSIZE; c++)
            if (CPU_ISSET(c, &set)) {
                char b[16];
                snprintf(b, sizeof b, "%s%d", first ? "" : ",", c);
                strncat(cpus, b, sizeof cpus - strlen(cpus) - 1);
                first = 0;
            }
    }

    double t_start = now_wall();
    if (dur > 0.0) {
        g_deadline = now_mono() + dur;
        int nth = ncores > 1 ? ncores : 1;
        if (nth > 256) nth = 256;
        pthread_t th[256];
        for (int i = 1; i < nth; i++) pthread_create(&th[i], NULL, spin, NULL);
        spin(NULL);
        for (int i = 1; i < nth; i++) pthread_join(th[i], NULL);
    }
    double t_end = now_wall();

    mkdir(outdir, 0777);  /* node-local dir; single level under /tmp, ignore EEXIST */

    char path[4096];
    snprintf(path, sizeof path, "%s/%s.json", outdir, uid);
    FILE *f = fopen(path, "w");
    if (!f) { perror("fopen"); return 1; }
    fprintf(f,
        "{\"uid\":\"%s\",\"host\":\"%s\",\"pid\":%d,\"cpus\":\"%s\","
        "\"ncores\":%d,\"dur\":%g,\"t_start\":%.6f,\"t_end\":%.6f}\n",
        uid, host, (int) getpid(), cpus, ncores, dur, t_start, t_end);
    fclose(f);
    return 0;
}
