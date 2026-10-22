# AmSC December 2026 demo: DTaaS for NSTX-U on STELLAR-AI

- **Event:** AmSC demo of the DTaaS "12-2026 Plan" (Vini's DTaaS
  capability deck, slide 2). Exact date and audience to be confirmed; this
  plan targets the week of Dec 14-18.
- **Commitment it delivers:** the year-2 milestone in the STELLAR-AI IP
  report, "NSTX-U data stream into a standing twin by December 2026".
- **Team:** Andre Merzky (DTaaS), Aymen Alsaadi (ROSE, fine-tuning), Vini
  Pillai (coordination, STELLAR-AI access), Matthew Baughman (NSTX-U models
  and data), Shantenu Jha.
- **Compute:** STELLAR-AI (`stellarai-amd.princeton.edu`, B200 nodes);
  Perlmutter as fallback.
- **Related:** the HPPSS demo (`2026-11-15-hppss-sc26.md`) builds parts of
  the same service stack; section 7 lists what carries over.
- **Status of this document:** plan as of 2026-10-22, to be agreed with
  Vini and Shantenu.

## 1. Scope (from the 12-2026 Plan)

1. Deploy DTaaS on STELLAR-AI.
2. DTaaS with IRI API integration on STELLAR-AI.
3. DTaaS for NSTX-U: launch with the NSTX-U world model and the GX
   surrogate.
4. Demonstrate prediction and fine-tuning with out-of-distribution (OOD)
   datasets.
5. Demonstrate streaming ingestion and prediction using NSTX-U shot data.

## 2. Demo flow

1. A laptop client creates an NSTX-U digital twin on the ORBIT broker
   (`dt` plugin). The twin's compute runs on a RHAPSODY endpoint on a
   STELLAR-AI B200 node, started through IRI if STELLAR-AI offers it
   (items 1, 2).
2. The twin loads the world model and the GX surrogate (item 3).
3. Archived NSTX-U shots are replayed as a stream into the twin; the twin
   predicts per shot. Shown with the time from shot data to prediction,
   measured against the 5-10 minute between-shot target (item 5).
4. The twin receives an OOD dataset: prediction error rises; a fine-tuning
   campaign runs on STELLAR-AI; the error before and after is shown
   (item 4).
5. The twin is torn down; the laptop shows an empty service.

## 3. Components: ready and missing

Status: **Ready** = exists and has been demonstrated; **Partial** = exists
but not merged or not tested in this configuration; **Missing** = to be
built or delivered.

| Component | Status | Where / evidence |
|---|---|---|
| DTaaS v1: ORBIT broker + `dt` plugin, sessions, reattach, teardown | Ready | `radical-cybertools/digital.twins` devel; standing deployment on radical.3 |
| Twin data plane over ORBIT pub/sub | Ready | digital.twins devel |
| Ex-situ learning in twins (ROSE `StreamingLearnerInvestigator`) | Ready | digital.twins devel |
| DT dashboard (live and replay) | Ready | digital.twins devel |
| RHAPSODY endpoint driven through ORBIT, with a twin on HPC | Ready on Perlmutter | dt-complete demo, recorded 2026-09 |
| Fine-tuning through RHAPSODY as a Service | Ready on Perlmutter | FTaaS path shown 2026-09-01 (SFAPI, not IRI) |
| STELLAR-AI access | Partial | Login host reachable over the Princeton VPN; account for `amerzky` not yet confirmed |
| Stack and RHAPSODY endpoint on STELLAR-AI B200 nodes | Missing | D3 |
| IRI API for STELLAR-AI | Missing | Not known whether STELLAR-AI offers one (D4) |
| NSTX-U world model and GX surrogate (checkpoints, inference code) | Missing | PPPL deliverable (D2) |
| Twin components wrapping both models | Missing | D5 |
| NSTX-U shot data (archived shots, access, format) | Missing | PPPL deliverable (D2) |
| Shot replay sensor and per-shot prediction | Missing | D6 |
| OOD dataset definition and data | Missing | PPPL deliverable (D2) |
| OOD prediction and fine-tuning campaign in the twin | Missing | D7 |
| Integrated run, runbook, slides, recorded fallback | Missing | D8, D9 |

## 4. Work items

| Id | Work item | Done when | Dates | Owner |
|---|---|---|---|---|
| D0 | Confirm demo date, audience, format (live or recorded) and scope with Vini | Date and scope fixed | Oct 26-30 | Andre |
| D1 | Verify STELLAR-AI access: login, Slurm account, B200 partition, outbound network from compute nodes to the broker | A test job on a B200 node reaches the broker | Oct 23-Nov 6 | Andre, Vini |
| D2 | Request from PPPL: world model and GX surrogate with inference code, OOD dataset definition and data, archived shot data with format | Requests sent Nov 6; deliveries by Nov 20 | Nov 2-20 | Vini, Matthew |
| D3 | Install the pinned stack on STELLAR-AI, start a RHAPSODY endpoint on a B200 node through ORBIT, run the DTaaS smoke test (`test/12-dtaas-live`) | Smoke test passes on STELLAR-AI | Nov 16-25 | Andre |
| D4 | IRI: if STELLAR-AI offers an IRI API, start the endpoint through it; otherwise start it through Slurm from ORBIT and say so in the demo | Endpoint starts from the client without an interactive login | Nov 23-Dec 4 | Andre |
| D5 | Wrap the world model and the GX surrogate as twin components, inference on B200 | Twin answers predictions from both models | Nov 20-Dec 4 | Aymen, Matthew |
| D6 | Shot replay sensor: archived shots streamed into the twin, per-shot prediction, time from shot to prediction recorded | Ten shots replayed with predictions and timings | Nov 23-Dec 7 | Andre |
| D7 | OOD prediction and fine-tuning: error on OOD data, fine-tuning campaign on STELLAR-AI, error after | Error before and after shown in the twin | Nov 30-Dec 11 | Aymen |
| D8 | Integrated run, timing, runbook | Three consecutive clean runs | Dec 7-11 | Andre |
| D9 | Slides and recorded fallback video | Reviewed by Vini and Shantenu | Dec 9-15 | Aymen, Andre |
| D10 | Demo | Delivered | week of Dec 14-18 (date TBD) | Shantenu or Vini |

## 5. Timeline

| Dates | Goal |
|---|---|
| Oct 23-Nov 15 | Prerequisites only, alongside the HPPSS demo: date and scope (D0), STELLAR-AI access (D1), PPPL requests (D2) |
| Nov 16-25 | DTaaS running on STELLAR-AI (D3) |
| Nov 20-Dec 7 | IRI path, NSTX-U models in the twin, shot replay (D4-D6) |
| Nov 30-Dec 11 | OOD prediction and fine-tuning; integrated run (D7, D8). Feature freeze Dec 11 |
| Dec 9-18 | Slides, fallback video, demo (D9, D10) |

## 6. Fallbacks

Each fallback is labelled as such in the demo.

| If | Then |
|---|---|
| STELLAR-AI not usable by Nov 25 | Run on Perlmutter (the path shown in the dt-complete demo); STELLAR-AI moves to Q1 2027 |
| No IRI API for STELLAR-AI | Start the endpoint through Slurm from ORBIT; IRI shown on Perlmutter only if the NERSC IRI facade works by then |
| Models late | Twin with the M3D-C1 surrogates from the dt-complete demo; world model and GX surrogate moved to Q1 2027 |
| Shot data late | Replay of synthetic shots in the shot-data format, if the format is known |
| OOD data late | OOD split of an existing dataset, chosen with Matthew |

## 7. Alignment with the HPPSS demo

Shared where the same software does the same job; not forced elsewhere.

| HPPSS work item | Reused in December |
|---|---|
| W7: install pins (RHAPSODY v0.6+, radex) and runbook | Base for the STELLAR-AI install (D3) |
| W4: start and stop the endpoint from the client through ORBIT | Endpoint start on STELLAR-AI, with or without IRI (D4) |
| W5: independent instances on one endpoint | Several twins or tenants on one STELLAR-AI endpoint |
| W2: radex store inside the remote endpoint (RHAPSODY PR #96) | Optional: cache replayed shot data next to inference (D6), only if the endpoint runs Dragon on STELLAR-AI |
| W10: recording practice and presenter notes | Fallback video (D9) |

Not shared: OpenFOAM and the Bayesian optimizer are HPPSS only; the
digital twin and the NSTX-U models are December only.

## 8. Risks

| Risk | Mitigation |
|---|---|
| STELLAR-AI account or network not ready | D1 starts now; Perlmutter fallback |
| PPPL deliverables (models, data) late | Requests by Nov 6 with Nov 20 due date; fallbacks in section 6 |
| Capacity: HPPSS until Nov 15 and the DT paper due end of December | Only prerequisites before Nov 15; D5 and D7 owned by Aymen and Matthew |
| Python and Dragon setup on STELLAR-AI differs from Perlmutter | Smoke test (D3) before any model work |

## 9. Open questions

- Demo date, audience and format (D0).
- Does STELLAR-AI offer an IRI API, and who operates it?
- Are compute nodes on STELLAR-AI allowed outbound connections to the
  broker (radical.3)?
- Who provides the world model and the GX surrogate, and in what form?
- Which signals make up "shot data" for the demo, and where are archived
  shots stored?
