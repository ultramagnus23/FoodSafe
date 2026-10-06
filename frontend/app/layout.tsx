import type { Metadata } from "next";
import { Familjen_Grotesk, Instrument_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Nav } from "@/components/Nav";
import { AuthModal } from "@/components/AuthModal";
import { MobileTabBar } from "@/components/MobileTabBar";
import { ChromeGate } from "@/components/ChromeGate";

const familjen = Familjen_Grotesk({ subsets: ["latin"], variable: "--font-familjen", display: "swap" });
const instrument = Instrument_Sans({ subsets: ["latin"], variable: "--font-instrument", display: "swap" });
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "FoodSafe India · food contamination to disease",
  description:
    "An open, evidence-linked engine from food contamination to disease: India's legal limits beside the EU, Codex and the US, what is found in food, the illnesses each hazard causes, and how places compare. Public records only.",
};

// Runs before hydration so the theme is correct on first paint (no
// light-flash-then-dark). Light is the default; dark is a deliberate,
// persisted choice, never a system-preference guess.
const themeInitScript = `
(function () {
  try {
    var stored = localStorage.getItem('foodsafe-theme');
    if (stored === 'dark') document.documentElement.classList.add('dark');
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${familjen.variable} ${instrument.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>
          <ChromeGate>
            <Nav />
          </ChromeGate>
          <div className="pb-16 lg:pb-0">
            {children}
            <ChromeGate>
              <footer className="flex flex-wrap items-center justify-between gap-6 border-t border-line px-8 py-10 text-xs text-provenance">
                <div className="max-w-md">
                  <strong className="font-display text-base text-ink">FoodSafe India</strong>
                  <br />
                  <span className="register">Public records only · not a laboratory service · not medical advice</span>
                  <br />
                  <span>
                    Open source:{" "}
                    <a className="underline" href="https://github.com/ultramagnus23/FoodSafe">
                      github.com/ultramagnus23/FoodSafe
                    </a>
                  </span>
                </div>
                <div className="register max-w-[420px] leading-relaxed sm:text-right">
                  Data: FSSAI · Lok Sabha · European Commission (RASFF, EU Pesticides Database) · FAO/WHO Codex · US eCFR ·
                  WHO · IARC · EFSA · World Bank · Open Food Facts · OpenAlex · Europe PMC
                </div>
              </footer>
            </ChromeGate>
          </div>
          <ChromeGate>
            <AuthModal />
            <MobileTabBar />
          </ChromeGate>
        </Providers>
      </body>
    </html>
  );
}
