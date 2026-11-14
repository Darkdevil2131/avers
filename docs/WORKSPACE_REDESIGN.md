# Research operations workspace

This revision changes the product interface, not the scientific capability of
the underlying agents. It uses a restrained dark palette, larger report text,
responsive role cards and inspectable real backend events.

Six roles show the implemented planner, collector, RAG retrieval, hypothesis
proposer, critic and persistent report workflow. Missing events remain explicitly
unobserved. Cancelled/failed runs do not leave roles active. Model rejection
remains visible even when replication proposals are subsequently generated.
These roles are policy-driven software and optional local inference, not six
independently validated scientific experts.

Collection activity displays a 3D spider/web motif; retrieval displays database
motion. The web is an activity illustration, not invented citation relationships.
Stored source nodes and highlighted citations still come from project records.
Reduced-motion and WebGL fallback views remain available.

Fixed a layout defect: global `aside` styling previously applied fixed-sidebar
positioning to proposal-review notes. Navigation styling now targets only the
application sidebar, while review notes remain within their report cards.

Validation: 14 UI component tests and the production build passed in the cloud
workspace. Four workflow tests cover empty state, observed activity, cancellation
and rejection followed by fallback. Scene rendering is mocked in workspace
tests; actual browser/WebGL visual acceptance remains unverified. The existing
large Three.js chunk warning remains. No model-intelligence improvement,
scientific acceptance, production deployment or completed master design is
claimed by this UI revision. No paid services, billing or trials are enabled.
