// V9: plain words for strength labels and claim types, from scoring.yaml via /reading-guide
// (the mirror ships reading_guide.json). Badges use them as tooltips; "How to read this" lists them.
import { createContext, useContext, useEffect, useState } from "react";
import { getReadingGuide, type Label, type ReadingGuide } from "./api";

export const GuideContext = createContext<ReadingGuide | null>(null);
export const useGuide = () => useContext(GuideContext);

export function useLoadGuide(): ReadingGuide | null {
  const [guide, setGuide] = useState<ReadingGuide | null>(null);
  useEffect(() => { getReadingGuide().then(setGuide).catch(() => setGuide(null)); }, []);
  return guide;
}

export const labelWords = (guide: ReadingGuide | null, label: Label) => guide?.labels[label]?.words;
