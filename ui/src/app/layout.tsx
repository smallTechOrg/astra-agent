import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Astra",
  description: "Operator dashboard for Astra agent",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
