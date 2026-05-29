import React from 'react';
import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

export default function ExportButtons({ targetId, title }) {
  const exportPNG = async () => {
    const node = document.getElementById(targetId);
    if (!node) return;
    const canvas = await html2canvas(node, { backgroundColor: '#f8fafc', scale: 2 });
    const link = document.createElement('a');
    link.download = `${title}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  };

  const exportPDF = async () => {
    const node = document.getElementById(targetId);
    if (!node) return;
    const canvas = await html2canvas(node, { backgroundColor: '#f8fafc', scale: 2 });
    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF('landscape', 'px', 'a4');
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = (canvas.height * pageWidth) / canvas.width;
    pdf.addImage(imgData, 'PNG', 0, 18, pageWidth, pageHeight);
    pdf.save(`${title}.pdf`);
  };

  return (
    <div className="actions-inline">
      <button className="secondary-button" onClick={exportPNG}>Export PNG</button>
      <button className="secondary-button" onClick={exportPDF}>Export PDF</button>
    </div>
  );
}
