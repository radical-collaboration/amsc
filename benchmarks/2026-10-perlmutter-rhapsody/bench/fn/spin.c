/* Busy-spin for `sec` seconds in pure C. Called via ctypes, which releases the
 * GIL for the duration, so N Python threads each calling spin() occupy N cores. */
#include <time.h>
double spin(double sec){
  struct timespec t0, t1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  volatile double x = 0.0;
  for(;;){
    for(int i=0;i<100000;i++) x += i*1.000001;   /* keep the core busy */
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double el = (t1.tv_sec-t0.tv_sec) + (t1.tv_nsec-t0.tv_nsec)*1e-9;
    if(el >= sec) return x;
  }
}
