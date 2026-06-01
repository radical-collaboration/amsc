# RADICAL Edge — executive summary

RADICAL Edge is a bridge-based framework that turns firewalled HPC
resources into programmable, network-reachable services.  It uses a
three-tier design — **client → bridge → edge** — in which a lightweight
edge service runs on the HPC side and dials *outbound* to a public bridge
over HTTPS/WebSockets, so a client (even a laptop with no public IP) can
drive remote compute through a uniform API without ever logging in.
Capabilities are exposed as plugins — HPC job submission (PsiJ), task
execution (Rhapsody on Dragon), system/queue info, file staging, and
on-demand spawning of further edges either directly or through facility
IRI endpoints — with real-time notifications streamed back to the client.
This inverts the usual HPC service model: rather than SSH-ing in,
submitting a batch script, and polling for output — or trying to expose
inbound ports on locked-down compute nodes — the edge connects out to a
rendezvous bridge, making the cluster behave like a service you *call*
instead of a host you *log into*.
