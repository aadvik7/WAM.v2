"use client";

import { useState } from "react";
import { ClinicTab } from "@/components/setup/ClinicTab";
import { DoctorsTab } from "@/components/setup/DoctorsTab";
import { FaqTab } from "@/components/setup/FaqTab";
import { PlansTab } from "@/components/setup/PlansTab";
import { StaffTab } from "@/components/setup/StaffTab";
import { ConnectionTab } from "@/components/setup/ConnectionTab";
import { UsersTab } from "@/components/setup/UsersTab";
import { Tabs } from "@/components/ui";

type Tab = "clinic" | "doctors" | "plans" | "faq" | "staff" | "whatsapp" | "users";

export default function SetupPage() {
  const [tab, setTab] = useState<Tab>("clinic");
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Setup</h1>
          <div className="muted">Hours, doctors, plan templates, FAQ, staff and the WhatsApp connection.</div>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "clinic", label: "Clinic" },
          { key: "doctors", label: "Doctors & hours" },
          { key: "plans", label: "Plan templates" },
          { key: "faq", label: "FAQ" },
          { key: "staff", label: "Staff & roles" },
          { key: "whatsapp", label: "WhatsApp connection" },
          { key: "users", label: "Admin users" },
        ]}
      />
      {tab === "clinic" && <ClinicTab />}
      {tab === "doctors" && <DoctorsTab />}
      {tab === "plans" && <PlansTab />}
      {tab === "faq" && <FaqTab />}
      {tab === "staff" && <StaffTab />}
      {tab === "whatsapp" && <ConnectionTab />}
      {tab === "users" && <UsersTab />}
    </div>
  );
}
