import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Real-Time Fatigue & Drowsiness Detection",
  description:
    "ML-powered fatigue monitoring using MediaPipe Face Mesh and CNN.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
