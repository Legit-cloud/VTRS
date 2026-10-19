import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { StatusChip } from "@/components/ui/chip";
import { ContestantBars, LeaderChip, toContestantRows } from "@/components/vtrs/contestant-bar";
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
      screen.getByText("Collected by our agents so far. Not the official INEC count."),
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

const PARTIES = [
  { party_id: "a", abbreviation: "APC", full_name: "A Party", ballot_order: 1, is_own: true, logo_url: null },
  { party_id: "b", abbreviation: "PDP", full_name: "B Party", ballot_order: 2, is_own: false, logo_url: null },
];
const VOTES = [
  { party_id: "a", abbreviation: "APC", candidate_id: "c1", candidate_name: "Ada Obi", votes: 600 },
  { party_id: "b", abbreviation: "PDP", candidate_id: "c2", candidate_name: "Bola Ade", votes: 400 },
];
const position = (status: "LEADING" | "NARROW" | "TIED" | "NO_VOTES", leading: string[]) => ({
  status,
  leader_party_id: status === "TIED" ? null : (leading[0] ?? null),
  leader_abbreviation: status === "TIED" ? null : "APC",
  runner_up_party_id: "b",
  leading_party_ids: leading,
  margin: 200,
  margin_pct: 20,
  total_votes: 1000,
  is_tie: status === "TIED",
  own_margin: 200,
});

describe("ContestantBars", () => {
  it("labels every party and marks only the leader provisional", () => {
    render(
      <ContestantBars rows={toContestantRows(VOTES, PARTIES)} position={position("LEADING", ["a"])} />,
    );
    expect(screen.getByText("Ada Obi")).toBeInTheDocument();
    expect(screen.getByText("PDP")).toBeInTheDocument();
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getAllByText("Provisional")).toHaveLength(1);
  });

  it("names a tie instead of a leader", () => {
    render(
      <ContestantBars rows={toContestantRows(VOTES, PARTIES)} position={position("TIED", ["a", "b"])} />,
    );
    expect(screen.queryByText("Provisional")).not.toBeInTheDocument();
    expect(screen.getAllByText("Tied")).toHaveLength(2);
  });
});

describe("LeaderChip", () => {
  it("says which parties are tied and flags a narrow margin", () => {
    const { rerender } = render(
      <LeaderChip position={position("TIED", ["a", "b"])} parties={PARTIES} />,
    );
    expect(screen.getByText("Tied: APC, PDP")).toBeInTheDocument();
    rerender(<LeaderChip position={position("NARROW", ["a"])} parties={PARTIES} />);
    expect(screen.getByText("APC")).toBeInTheDocument();
    expect(screen.getByText("Narrow margin")).toBeInTheDocument();
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

describe("cn", () => {
  it("keeps a text colour next to a design-system type size", async () => {
    const { cn } = await import("@/lib/cn");
    expect(cn("text-primary-foreground", "text-body")).toBe("text-primary-foreground text-body");
    expect(cn("text-body", "text-label")).toBe("text-label");
  });
});
