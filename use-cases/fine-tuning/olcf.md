# OLCF compute-egress gap for distributed applications

## The constraint

On OLCF Frontier-class hardware (incl. the `odo` IRI resource), compute
nodes cannot initiate outbound network connections — not to the public
internet, not to a login node within the site. The only direction that
works on the SSH path is **login → compute**. NERSC / Aurora / Perlmutter
allow the opposite (compute → login outbound).

## Affected pattern

Any distributed application whose compute-side processes need to reach a
service outside the allocation hits this. Worked example: the **AmSC
fine-tuning demo**, where a compute-side service needs a persistent TLS
WebSocket to a public bridge to receive task submissions and return
results. Same shape as a trainer streaming intermediate metrics to an
off-site collector, a task pulling a model checkpoint from a public
registry on startup, or a workload coordinator calling back to a control
plane in the user's environment.

## What does not work

| Approach | Why it fails on OLCF |
|---|---|
| Direct outbound from compute (HTTPS, custom port, anything) | Compute egress is blocked. |
| `ssh -L` (forward tunnel) from compute through a login node | Compute → login SSH is blocked too. |
| `ssh -R` (reverse tunnel) set up by the compute job itself | Same — compute can't reach the login to initiate it. |
| A "submit and walk away" submission API (e.g. an IRI-launched job with no follow-on actor) | The job runs, but nothing on the login side knows the compute hostname and ports, so the login → compute reverse tunnel that *would* work is never established. |
| Co-locating the destination service inside the allocation | Doesn't help any consumer outside the allocation (the user, a public registry, a cloud collector). |

Net: distributed-app patterns that work transparently on NERSC / Aurora /
Perlmutter need a separate arrangement at OLCF, because **both endpoints
of the tunnel that would carry the traffic have to be brokered from the
login side**, and a submission-only path supplies no such broker.
