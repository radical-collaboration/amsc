#!/usr/bin/env python3
"""Raw dragon dispatch ceiling (no rhapsody, no record I/O): dragon's native
multiprocessing Pool mapping a no-op. Run: dragon python fn_recon.py --count K --procs P
"""
import argparse, time
import dragon                      # noqa: F401  (registers the dragon start method)
import multiprocessing as mp


def noop(x):
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200000)
    ap.add_argument("--procs", type=int, default=256)
    a = ap.parse_args()
    mp.set_start_method("dragon", force=True)
    pool = mp.Pool(processes=a.procs)
    pool.map(noop, range(2000))     # warmup
    for cs in (1, 64):
        t = time.perf_counter()
        pool.map(noop, range(a.count), chunksize=cs)
        dt = time.perf_counter() - t
        print(f"RAW dragon mp.Pool noop: count={a.count} procs={a.procs} "
              f"chunksize={cs} -> {a.count/dt:.0f}/s ({dt:.1f}s)", flush=True)
    pool.close(); pool.join()


if __name__ == "__main__":
    main()
