import type { Metadata } from "next";
import { InstallBox, SiteFooter, TopNav } from "@/components/marketing/site-chrome";
import { PageHero } from "@/components/marketing/page-hero";

const LEDE =
  "If an Airflow provider is installed, DTE can use its connections. IAM roles, service accounts and secrets backends work the same as in your other DAGs.";

export const metadata: Metadata = {
  title: "Integrations",
  description: LEDE,
  alternates: { canonical: "/integrations/" },
};

// What ships in dte-airflow today — keep in step with the README's feature tables.
export default function Page() {
  return (
    <div className="site">
      <TopNav current="integrations" />
      <main>
        <PageHero title="Uses the connections" hi="you already have" lede={LEDE} />
        <section className="s"><div className="in">
          <div className="eco"><div className="eco-grid">
      <div className="col"><span className="hd">Sources</span>
        <div className="grp"><b>Files</b><div className="chips"><span>S3</span><span>GCS</span><span>Azure</span><span>SFTP</span><span>PDF</span></div></div>
        <div className="grp"><b>Databases</b><div className="chips"><span>Postgres</span><span>MySQL</span><span>SQL Server</span><span>MongoDB</span></div></div>
        <div className="grp"><b>Warehouses + APIs</b><div className="chips"><span>Snowflake</span><span>BigQuery</span><span>REST</span></div></div>
      </div>
      <div className="wire"></div>
      <div className="core"><span className="logo"><i />dte</span><small>inside Apache Airflow 3</small></div>
      <div className="wire"></div>
      <div className="col"><span className="hd">Destinations</span>
        <div className="grp"><b>Databases</b><div className="chips"><span>Postgres</span><span>MySQL</span><span>SQL Server</span></div></div>
        <div className="grp"><b>Warehouses</b><div className="chips"><span>Snowflake</span><span>BigQuery</span></div></div>
        <div className="grp"><b>Files</b><div className="chips"><span>Parquet</span><span>CSV</span><span>Excel</span><span>JSON</span></div></div>
      </div>
    </div></div>
        </div></section>
        <section className="s" id="install"><div className="in"><InstallBox /></div></section>
      </main>
      <SiteFooter />
    </div>
  );
}
