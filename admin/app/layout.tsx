import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WAM admin",
  description: "Setup, patients, today's list and reports for WAM, the WhatsApp assistant that brings patients back.",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
