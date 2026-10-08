param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
# Windows Common Item Dialog: https://learn.microsoft.com/windows/win32/shell/common-file-dialog
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public static class CareerForgePicker {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct Filter { [MarshalAs(UnmanagedType.LPWStr)] public string Name; [MarshalAs(UnmanagedType.LPWStr)] public string Spec; }
    [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")] class FileOpenDialog { }
    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItem {
        void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr result);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint type, out IntPtr name);
        void GetAttributes(uint mask, out uint attributes);
        void Compare(IShellItem other, uint hint, out int order);
    }
    [ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IFileDialog {
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, [MarshalAs(UnmanagedType.LPArray, SizeParamIndex=0)] Filter[] filters);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder(IShellItem folder);
        void SetFolder(IShellItem folder);
        void GetFolder(out IShellItem folder);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
        void AddPlace(IShellItem item, uint alignment);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
        void Close(int result);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr filter);
    }
    [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
    static extern void SHCreateItemFromParsingName(string path, IntPtr context, ref Guid id, out IShellItem item);
    public static string Pick(bool folder, string initial, string title, bool validateOnly) {
        IFileDialog dialog = (IFileDialog)new FileOpenDialog();
        try {
            uint options; dialog.GetOptions(out options);
            dialog.SetOptions(options | 0x40u | 0x800u | 0x1000u | 0x02000000u | (folder ? 0x20u : 0u));
            dialog.SetTitle(title);
            dialog.SetOkButtonLabel(folder ? "Select folder" : "Select document");
            if (!folder) dialog.SetFileTypes(1, new Filter[] { new Filter { Name="OpenDocument Text (*.odt)", Spec="*.odt" } });
            if (!String.IsNullOrEmpty(initial)) {
                Guid iid = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"); IShellItem start;
                SHCreateItemFromParsingName(initial, IntPtr.Zero, ref iid, out start);
                try { dialog.SetFolder(start); } finally { Marshal.ReleaseComObject(start); }
            }
            if (validateOnly) return "validated";
            using (Form owner = new Form()) {
                owner.ShowInTaskbar = false; owner.Opacity = 0; owner.TopMost = true;
                owner.StartPosition = FormStartPosition.CenterScreen; owner.Show();
                int result = dialog.Show(owner.Handle);
                if (result == unchecked((int)0x800704C7)) return null;
                Marshal.ThrowExceptionForHR(result);
                IShellItem item; dialog.GetResult(out item);
                try {
                    IntPtr path; item.GetDisplayName(0x80058000, out path);
                    try { return Marshal.PtrToStringUni(path); } finally { Marshal.FreeCoTaskMem(path); }
                } finally { Marshal.ReleaseComObject(item); }
            }
        } finally { Marshal.ReleaseComObject(dialog); }
    }
}
'@
if ($ValidateOnly) {
    [CareerForgePicker]::Pick($true, '', 'CareerForge picker validation', $true)
    [CareerForgePicker]::Pick($false, '', 'CareerForge picker validation', $true)
    exit 0
}
$pickerRequest = [Console]::In.ReadToEnd() | ConvertFrom-Json
$pickedPath = [CareerForgePicker]::Pick([bool]$pickerRequest.folder, [string]$pickerRequest.initial, [string]$pickerRequest.title, $false)
@{ selected = $pickedPath; canceled = ($null -eq $pickedPath) } | ConvertTo-Json -Compress
