import Script from "next/script";
import type { Metadata } from "next";
import { Outfit, Space_Mono, Cormorant_Garamond, Bricolage_Grotesque, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SITE_URL, SITE_NAME, SITE_TITLE, SITE_DESCRIPTION, REPO_URL } from "@/lib/site";

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

const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  weight: ["400", "700"],
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
    "Apache Airflow",
    "Airflow plugin",
    "Airflow 3",
    "open source",
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
  operatingSystem: "Any (self-hosted on Apache Airflow 3)",
  license: "https://www.apache.org/licenses/LICENSE-2.0",
  isAccessibleForFree: true,
  description: SITE_DESCRIPTION,
  url: SITE_URL,
  sameAs: [REPO_URL],
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
    url: REPO_URL,
  },
  featureList: [
    "Runs as an Apache Airflow 3 plugin: every pipeline is an Airflow DAG",
    "Sources: local files, S3, GCS, Azure Blob, SFTP, Postgres, MySQL, SQL Server, Snowflake, BigQuery, MongoDB, REST APIs, PDFs",
    "Destinations: Postgres, MySQL, SQL Server, Snowflake, BigQuery, Parquet/JSON/CSV/Excel files locally or in object storage",
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
      className={`${outfit.variable} ${spaceMono.variable} ${cormorant.variable} ${bricolage.variable} ${geistMono.variable}`}
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
