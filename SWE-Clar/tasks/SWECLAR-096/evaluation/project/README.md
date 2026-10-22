# Area calculator component

Repair the supplied responsive web calculator and Python backend. `python server.py` starts a loopback service (PORT=0 chooses a free port and prints JSON). The browser sends numeric land_area_sqft, site_area_sqft and plot_ratio inputs to POST /calculate; POST /report returns an actual downloadable PDF. The frontend must display returned values and keep the calculation on the backend rather than embedding formula code in browser assets.

This component reconstructs the source-supported area calculation workflow. It is not the complete property valuation spreadsheet or a mobile-store release. The selected formula snapshot and output formatting are defined by the requirement registry; later commercial revisions are outside this component. All fixtures use synthetic numeric inputs and omit project names, site information, original files and links. Prepared Python 3.12, reportlab 4.4.9 and browser dependencies are provided; no external network or account is required.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
