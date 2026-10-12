// ISO 3166-2:NG short codes, which is what the master-data directories use.
export const STATE_NAMES: Record<string, string> = {
  AB: "Abia",
  AD: "Adamawa",
  AK: "Akwa Ibom",
  AN: "Anambra",
  BA: "Bauchi",
  BY: "Bayelsa",
  BE: "Benue",
  BO: "Borno",
  CR: "Cross River",
  DE: "Delta",
  EB: "Ebonyi",
  ED: "Edo",
  EK: "Ekiti",
  EN: "Enugu",
  FC: "FCT",
  GO: "Gombe",
  IM: "Imo",
  JI: "Jigawa",
  KD: "Kaduna",
  KN: "Kano",
  KT: "Katsina",
  KE: "Kebbi",
  KO: "Kogi",
  KW: "Kwara",
  LA: "Lagos",
  NA: "Nasarawa",
  NI: "Niger",
  OG: "Ogun",
  ON: "Ondo",
  OS: "Osun",
  OY: "Oyo",
  PL: "Plateau",
  RI: "Rivers",
  SO: "Sokoto",
  TA: "Taraba",
  YO: "Yobe",
  ZA: "Zamfara",
};

/** "Oyo State" for a directory code such as `DIR-OY`; the synthetic test set is `SYN`. */
export function stateName(code: string | undefined): string {
  if (!code) return "State";
  // Directory imports prefix the short code (DIR-OY); the synthetic test set is SYN.
  const short = code.toUpperCase().replace(/^DIR-/, "");
  if (short === "SYN") return "Test state";
  const name = STATE_NAMES[short];
  return name ? (name === "FCT" ? "FCT" : `${name} State`) : code;
}
