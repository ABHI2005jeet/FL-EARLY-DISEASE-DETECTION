import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Federated Disease Detection",
  description: "Federated learning dashboard scaffold",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
