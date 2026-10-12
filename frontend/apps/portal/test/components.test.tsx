import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { StatusChip } from "@/components/ui/chip";
import { CandidateBars } from "@/components/vtrs/candidate-bar";
import { CoverageChart, coverageStyle } from "@/components/vtrs/coverage";
import { DataTable } from "@/components/vtrs/data-table";
import { ProvisionalBadge } from "@/components/vtrs/provisional";
import { StatTile } from "@/components/vtrs/stat-tile";
import { TallyMeter } from "@/components/vtrs/tally-meter";
import { Timeline } from "@/components/vtrs/timeline";

describe("TallyMeter", () => {
  it("draws one mark per unit and says how many reported", () => {
    const { container } = render(<TallyMeter reported={17} total={24} />);
    expect(container.querySelectorAll("svg line")).toHaveLength(24);
    expect(screen.getByRole("img", { name: "17 of 24 reported" })).toBeInTheDocument();
  });

  it("falls back to a progress bar above 60 units", () => {
    render(<TallyMeter reported={30} total={90} />);
    const bar = screen.getByRole("progressbar", { name: "30 of 90 reported" });
    expect(bar).toHaveAttribute("aria-valuenow", "30");
  });
});

describe("Provisional badge", () => {
  it("always carries the word, with the caption on request", () => {
    render(<ProvisionalBadge caption />);
    expect(screen.getByText("Provisional")).toBeInTheDocument();
    expect(
      screen.getByText("Based on results reported so far. Not the official declaration."),
    ).toBeInTheDocument();
  });
});

describe("StatusChip", () => {
  it("shows an icon and a word, never colour alone", () => {
    const { container } = render(
      <StatusChip status={{ label: "Needs review", tone: "amber", icon: "flag" }} />,
    );
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("CandidateBars", () => {
  it("labels every bar and marks the leader provisional", () => {
    render(
      <CandidateBars
        rows={[
          { id: "a", name: "Ada Obi", party: "APC", votes: 600, own: true, leader: true },
          { id: "b", name: "Bola Ade", party: "PDP", votes: 400 },
        ]}
      />,
    );
    expect(screen.getByText("Ada Obi")).toBeInTheDocument();
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getAllByText("Provisional")).toHaveLength(1);
  });
});

describe("coverage scale", () => {
  it("treats no reports as its own dashed state, not as zero percent teal", () => {
    expect(coverageStyle(0, 0).className).toContain("border-dashed");
    expect(coverageStyle(10, 3).className).toContain("bg-teal-200");
    expect(coverageStyle(80, 40).className).toContain("bg-teal-800");
  });

  it("gives the chart a text summary and a table alternative", () => {
    render(
      <CoverageChart
        expected={100}
        points={[
          { at: "2026-10-12T08:00:00Z", newly_reported: 10, cumulative: 10 },
          { at: "2026-10-12T09:00:00Z", newly_reported: 40, cumulative: 50 },
        ]}
      />,
    );
    expect(
      screen.getByRole("img", { name: /50\.0% of 100 polling units reported/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Show as a table")).toBeInTheDocument();
  });
});

describe("StatTile", () => {
  it("exposes progress to assistive tech", () => {
    render(<StatTile emphasized value="81.6%" label="Polling units reported" progress={81.6} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "82");
  });
});

describe("DataTable", () => {
  const rows = [
    { id: "1", name: "Ibadan North", reported: 40 },
    { id: "2", name: "Akinyele", reported: 90 },
    { id: "3", name: "Oluyole", reported: 10 },
  ];
  const columns = [
    {
      key: "name",
      header: "LGA",
      cell: (r: (typeof rows)[number]) => r.name,
      sortValue: (r: (typeof rows)[number]) => r.name,
    },
    {
      key: "reported",
      header: "Reported",
      numeric: true,
      cell: (r: (typeof rows)[number]) => r.reported,
      sortValue: (r: (typeof rows)[number]) => r.reported,
    },
  ];

  it("sorts by a column and reports the order to assistive tech", async () => {
    render(
      <DataTable caption="LGAs" columns={columns} rows={rows} rowKey={(r) => r.id} empty={null} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Reported/ }));
    const body = screen.getAllByRole("row").slice(1);
    expect(within(body[0]!).getByText("Akinyele")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Reported/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("opens a row from the keyboard", async () => {
    let opened = "";
    render(
      <DataTable
        caption="LGAs"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        empty={null}
        onRowClick={(r) => (opened = r.name)}
      />,
    );
    const row = screen.getByText("Oluyole").closest("tr")!;
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(opened).toBe("Oluyole");
  });

  it("shows the empty state inside the table area, never a blank body", () => {
    render(
      <DataTable
        caption="LGAs"
        columns={columns}
        rows={[]}
        rowKey={(r: (typeof rows)[number]) => r.id}
        empty={<p>Nothing here yet</p>}
      />,
    );
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
  });
});

describe("Timeline", () => {
  it("lists entries in order with who and when", () => {
    render(
      <Timeline
        items={[
          { id: "1", title: "Raised", meta: "12 Oct 2026, 14:05", system: true },
          { id: "2", title: "Acknowledged", meta: "12 Oct 2026, 14:20" },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("Raised")).toBeInTheDocument();
  });
});
