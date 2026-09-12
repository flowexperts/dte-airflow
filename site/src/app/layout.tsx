import Script from "next/script";
import type { Metadata } from "next";
import { Outfit, Space_Mono, Cormorant_Garamond } from "next/font/google";
import "./globals.css";
import { SITE_URL, SITE_NAME, SITE_TITLE, SITE_DESCRIPTION } from "@/lib/site";

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const spaceMono = Space_Mono({
  variable: "--font-space-mono",
  subsets: ["latin"],
  weight: ["400", "700"],
});

const cormorant = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["500"],
  style: ["italic"],
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_TITLE,
    template: `%s — ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  keywords: [
    "data transformation engine",
    "ETL",
    "ELT",
    "data pipeline builder",
    "no-code data pipeline",
    "DuckDB",
    "ibis",
    "data quality checks",
    "S3 to Postgres",
    "REST API to data warehouse",
  ],
  applicationName: SITE_NAME,
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: SITE_NAME,
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: SITE_NAME,
  alternateName: "Data Transformation Engine",
  applicationCategory: "DataTransformationApplication",
  operatingSystem: "Any (self-hosted / cloud)",
  description: SITE_DESCRIPTION,
  url: SITE_URL,
  offers: {
    "@type": "Offer",
    availability: "https://schema.org/InStock",
    url: `${SITE_URL}/#book`,
  },
  featureList: [
    "Sources: S3, GCS, Azure Blob, Postgres, MongoDB, REST APIs, local filesystem",
    "Destinations: Postgres, SQL databases, Parquet on S3, JSON/CSV/Excel files, REST endpoint",
    "No-code pipeline builder: filter, rename, retype, lookup, aggregate, join, pivot, select/drop",
    "Data quality: check, profile, and dry-run preview before every run",
  ],
};

const GA_ID = "G-VM70DMGFX7";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-theme="dark"
      className={`${outfit.variable} ${spaceMono.variable} ${cormorant.variable}`}
    >
      <body>
        {/* Google Analytics — afterInteractive so it never blocks first paint. */}
        <Script async src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`} />
        <Script id="gtag-init" strategy="afterInteractive">
          {`window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', '${GA_ID}');`}
        </Script>
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        {children}
      </body>
    </html>
  );
}
