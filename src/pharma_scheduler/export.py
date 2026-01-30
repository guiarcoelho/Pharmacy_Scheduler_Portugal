"""Export and reporting functionality.

This module handles:
- CSV export (schedule and worker stats)
- Optional Excel export
- Console pretty printing
"""

from pathlib import Path
from typing import Optional
import pandas as pd


class Exporter:
    """Export scheduler results to various formats."""

    def __init__(self, output_dir: str):
        """Initialize exporter.

        Args:
            output_dir: Directory to write output files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_csv(self, solution: pd.DataFrame, stats: pd.DataFrame):
        """Export solution and statistics to CSV.

        Args:
            solution: Solution DataFrame with assignments
            stats: Statistics DataFrame with per-worker metrics
        """
        # Filter to report range only
        report_solution = solution[solution['in_report_range']].copy()

        # Schedule CSV
        schedule_df = report_solution[[
            'date', 'day_tags', 'shift', 'worker']].copy()
        schedule_df = schedule_df.sort_values(['date', 'shift', 'worker'])

        schedule_path = self.output_dir / 'schedule.csv'
        schedule_df.to_csv(schedule_path, index=False)
        print(f"✓ Wrote schedule to {schedule_path}")

        # Worker stats CSV
        stats_path = self.output_dir / 'worker_stats.csv'
        stats.to_csv(stats_path, index=False)
        print(f"✓ Wrote worker statistics to {stats_path}")

    def export_excel(self, solution: pd.DataFrame, stats: pd.DataFrame):
        """Export solution and statistics to Excel.

        Args:
            solution: Solution DataFrame with assignments
            stats: Statistics DataFrame with per-worker metrics
        """
        try:
            import openpyxl
        except ImportError:
            print("⚠ openpyxl not installed, skipping Excel export")
            return

        excel_path = self.output_dir / 'schedule.xlsx'

        # Filter to report range
        report_solution = solution[solution['in_report_range']].copy()

        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # Grid view (requested by user): Rows = Workers, Columns = Dates
            grid_df = report_solution.pivot(
                index='worker', columns='date', values='shift')
            # Fill NaNs with "OFF"
            grid_df = grid_df.fillna('OFF')
            grid_df.to_excel(writer, sheet_name='Grid')

            # Schedule sheet
            schedule_df = report_solution[[
                'date', 'day_tags', 'shift', 'shift_name', 'worker']].copy()
            schedule_df = schedule_df.sort_values(['date', 'shift', 'worker'])
            schedule_df.to_excel(writer, sheet_name='Schedule', index=False)

            # Worker stats sheet
            stats.to_excel(writer, sheet_name='Worker Statistics', index=False)

            # Summary sheet
            summary_data = {
                'Metric': [
                    'Total assignments',
                    'Date range',
                    'Number of workers',
                    'Total paid hours'
                ],
                'Value': [
                    len(report_solution),
                    f"{report_solution['date'].min()} to {report_solution['date'].max()}",
                    len(stats),
                    f"{stats['total_hours'].sum():.1f}"
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

        print(f"✓ Wrote Excel workbook to {excel_path}")

    def print_summary(self, solution: pd.DataFrame, stats: pd.DataFrame,
                      objective_value: Optional[float] = None):
        """Print summary to console.

        Args:
            solution: Solution DataFrame
            stats: Statistics DataFrame
            objective_value: Objective value if available
        """
        report_solution = solution[solution['in_report_range']]

        print("\n" + "="*78)
        print("SCHEDULE SUMMARY")
        print("="*78)

        print(
            f"\nDate range: {report_solution['date'].min()} to {report_solution['date'].max()}")
        print(f"Total assignments: {len(report_solution)}")
        print(f"Total paid hours: {stats['total_hours'].sum():.1f}")

        if objective_value is not None:
            print(f"\nObjective value: {objective_value:.0f}")

        print("\n" + "-"*78)
        print("WORKER STATISTICS")
        print("-"*78)

        # Format stats for display
        cols_to_show = ['worker', 'total_hours', 'total_shifts',
                        'days_off', 'sundays_worked', 'full_weekends_off']
        display_stats = stats[cols_to_show].copy()

        print(display_stats.to_string(index=False))

        print("\n" + "="*78)

    def print_schedule_by_date(self, solution: pd.DataFrame):
        """Print schedule organized by date.

        Args:
            solution: Solution DataFrame
        """
        report_solution = solution[solution['in_report_range']].sort_values(
            'date')

        print("\n" + "="*78)
        print("SCHEDULE BY DATE")
        print("="*78)

        for date in report_solution['date'].unique():
            day_schedule = report_solution[report_solution['date'] == date]
            day_tags = day_schedule.iloc[0]['day_tags']
            print(f"\n{date} ({date.strftime('%A')}) - {day_tags}")
            print("-" * 40)

            for _, row in day_schedule.iterrows():
                print(
                    f"  {row['shift']:4s} ({row['shift_name']:25s}): {row['worker']}")
