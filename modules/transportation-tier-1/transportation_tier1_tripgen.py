"""
Transportation Tier 1: Trip Generation Module

Calculates vehicle trip generation based on ITE (Institute of Transportation Engineers) methodology.
Takes proposed land uses and sizes as input, applies standard trip generation rates.
"""
import json
from pathlib import Path


def execute(inputs):
    """
    Execute trip generation analysis using ITE methodology

    Args:
        inputs (dict): Dictionary containing:
            - land_uses: Array of land use objects with ite_code, size, size_unit
            - jurisdiction (optional): Jurisdiction for adjustments (default: "generic")
            - analysis_period (optional): "daily", "am_peak", "pm_peak", or "all" (default: "all")

    Returns:
        dict: Trip generation results with totals, breakdown, summary, and visualization
    """
    # Parse inputs
    land_uses = inputs.get('land_uses')
    jurisdiction = inputs.get('jurisdiction', 'generic')
    analysis_period = inputs.get('analysis_period', 'all')

    # Validate inputs
    if not land_uses:
        raise ValueError("land_uses is required")

    if not isinstance(land_uses, list):
        raise ValueError("land_uses must be an array of land use objects")

    if len(land_uses) == 0:
        raise ValueError("land_uses array cannot be empty")

    # Load ITE rates
    rates_path = Path(__file__).parent / 'ite_rates.json'
    with open(rates_path, 'r') as f:
        ite_rates = json.load(f)

    # Calculate trips for each land use
    trip_breakdown = []
    total_daily = 0
    total_am_peak = 0
    total_pm_peak = 0

    for land_use in land_uses:
        ite_code = str(land_use.get('ite_code', ''))
        size = land_use.get('size', 0)
        name = land_use.get('name', f'Land Use {ite_code}')

        if not ite_code:
            raise ValueError(f"ite_code is required for land use: {name}")

        if ite_code not in ite_rates:
            raise ValueError(f"ITE code {ite_code} not found in rate table. Available codes: {', '.join(ite_rates.keys())}")

        rate_data = ite_rates[ite_code]

        # Calculate trips based on rates
        daily_trips = size * rate_data['daily_rate']
        am_peak_trips = size * rate_data['am_peak_rate']
        pm_peak_trips = size * rate_data['pm_peak_rate']

        # Add to totals
        total_daily += daily_trips
        total_am_peak += am_peak_trips
        total_pm_peak += pm_peak_trips

        # Store breakdown
        trip_breakdown.append({
            'ite_code': ite_code,
            'name': name,
            'land_use_type': rate_data['name'],
            'size': size,
            'size_unit': rate_data['size_unit'],
            'daily_trips': round(daily_trips, 2),
            'am_peak_trips': round(am_peak_trips, 2),
            'pm_peak_trips': round(pm_peak_trips, 2)
        })

    # Generate summary report
    summary_report = generate_summary_report(
        trip_breakdown,
        total_daily,
        total_am_peak,
        total_pm_peak,
        jurisdiction,
        analysis_period
    )

    # Generate HTML visualization
    visualization_html = generate_visualization(
        trip_breakdown,
        total_daily,
        total_am_peak,
        total_pm_peak,
        analysis_period
    )

    # Prepare outputs
    outputs = {
        'total_daily_trips': round(total_daily, 2),
        'am_peak_trips': round(total_am_peak, 2),
        'pm_peak_trips': round(total_pm_peak, 2),
        'trip_breakdown': trip_breakdown,
        'summary_report': summary_report,
        'visualization': visualization_html
    }

    return outputs


def generate_summary_report(breakdown, total_daily, total_am, total_pm, jurisdiction, period):
    """Generate formatted text summary report"""

    report = """Transportation Tier 1: Trip Generation Analysis
================================================

"""

    if jurisdiction != 'generic':
        report += f"Jurisdiction: {jurisdiction.upper()}\n"

    report += f"Analysis Period: {period.replace('_', ' ').title()}\n"
    report += f"Number of Land Uses: {len(breakdown)}\n\n"

    report += "TRIP GENERATION SUMMARY\n"
    report += "=" * 50 + "\n\n"

    # Detailed breakdown
    for item in breakdown:
        report += f"{item['name']} (ITE {item['ite_code']})\n"
        report += f"  Type: {item['land_use_type']}\n"
        report += f"  Size: {item['size']} {item['size_unit'].replace('_', ' ')}\n"

        if period in ['all', 'daily']:
            report += f"  Daily Trips: {item['daily_trips']:,.2f}\n"
        if period in ['all', 'am_peak']:
            report += f"  AM Peak Trips: {item['am_peak_trips']:,.2f}\n"
        if period in ['all', 'pm_peak']:
            report += f"  PM Peak Trips: {item['pm_peak_trips']:,.2f}\n"
        report += "\n"

    # Totals
    report += "TOTAL TRIP GENERATION\n"
    report += "=" * 50 + "\n"

    if period in ['all', 'daily']:
        report += f"Total Daily Trips: {total_daily:,.2f} vehicle trips/day\n"
    if period in ['all', 'am_peak']:
        report += f"AM Peak Hour Trips: {total_am:,.2f} vehicle trips/hour\n"
    if period in ['all', 'pm_peak']:
        report += f"PM Peak Hour Trips: {total_pm:,.2f} vehicle trips/hour\n"

    report += "\n"
    report += "Note: Rates based on ITE Trip Generation Manual, 11th Edition.\n"
    report += "Trip ends represent total entering + exiting vehicles.\n"

    return report


def generate_visualization(breakdown, total_daily, total_am, total_pm, period):
    """Generate HTML table visualization"""

    html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            padding: 20px;
            background: #f9fafb;
        }
        h2 {
            color: #111827;
            margin-bottom: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-radius: 8px;
            overflow: hidden;
        }
        th {
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            font-size: 14px;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #e5e7eb;
            font-size: 14px;
        }
        tr:last-child td {
            border-bottom: none;
        }
        tr:hover {
            background: #f3f4f6;
        }
        .numeric {
            text-align: right;
            font-family: 'Courier New', monospace;
        }
        .total-row {
            background: #f9fafb;
            font-weight: 600;
            border-top: 2px solid #667eea;
        }
        .total-row td {
            padding: 14px 12px;
        }
        .code {
            font-family: 'Courier New', monospace;
            background: #e5e7eb;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
        }
        .footer {
            margin-top: 20px;
            font-size: 12px;
            color: #6b7280;
        }
    </style>
</head>
<body>
    <h2>Trip Generation Results</h2>
    <table>
        <thead>
            <tr>
                <th>Land Use</th>
                <th>ITE Code</th>
                <th>Size</th>
"""

    # Column headers based on analysis period
    if period in ['all', 'daily']:
        html += "                <th class='numeric'>Daily Trips</th>\n"
    if period in ['all', 'am_peak']:
        html += "                <th class='numeric'>AM Peak</th>\n"
    if period in ['all', 'pm_peak']:
        html += "                <th class='numeric'>PM Peak</th>\n"

    html += """            </tr>
        </thead>
        <tbody>
"""

    # Data rows
    for item in breakdown:
        size_display = f"{item['size']:,.0f} {item['size_unit'].replace('_', ' ')}"
        html += f"""            <tr>
                <td>{item['name']}<br><small style="color: #6b7280;">{item['land_use_type']}</small></td>
                <td><span class="code">{item['ite_code']}</span></td>
                <td>{size_display}</td>
"""

        if period in ['all', 'daily']:
            html += f"                <td class='numeric'>{item['daily_trips']:,.2f}</td>\n"
        if period in ['all', 'am_peak']:
            html += f"                <td class='numeric'>{item['am_peak_trips']:,.2f}</td>\n"
        if period in ['all', 'pm_peak']:
            html += f"                <td class='numeric'>{item['pm_peak_trips']:,.2f}</td>\n"

        html += "            </tr>\n"

    # Total row
    html += """            <tr class="total-row">
                <td colspan="2"><strong>TOTAL</strong></td>
                <td></td>
"""

    if period in ['all', 'daily']:
        html += f"                <td class='numeric'><strong>{total_daily:,.2f}</strong></td>\n"
    if period in ['all', 'am_peak']:
        html += f"                <td class='numeric'><strong>{total_am:,.2f}</strong></td>\n"
    if period in ['all', 'pm_peak']:
        html += f"                <td class='numeric'><strong>{total_pm:,.2f}</strong></td>\n"

    html += """            </tr>
        </tbody>
    </table>
    <div class="footer">
        Trip generation rates based on ITE Trip Generation Manual, 11th Edition.<br>
        Values represent vehicle trip ends (total entering + exiting vehicles).
    </div>
</body>
</html>
"""

    return html


# For testing
if __name__ == '__main__':
    # Sample test data
    test_inputs = {
        'land_uses': [
            {
                'ite_code': '220',
                'name': 'Residential Building',
                'size': 100,
                'size_unit': 'dwelling_units'
            },
            {
                'ite_code': '710',
                'name': 'Office Building',
                'size': 50,
                'size_unit': '1000_sqft'
            }
        ],
        'jurisdiction': 'generic',
        'analysis_period': 'all'
    }

    result = execute(test_inputs)
    print(result['summary_report'])
    print(f"\nTotal Daily Trips: {result['total_daily_trips']}")
    print(f"AM Peak Trips: {result['am_peak_trips']}")
    print(f"PM Peak Trips: {result['pm_peak_trips']}")
