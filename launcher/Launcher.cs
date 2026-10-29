// Local owner console; backend and bot code remain in the updatable project.
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
[assembly: AssemblyTitle("ZhBot Launcher")]
[assembly: AssemblyVersion("1.0.0.0")]
internal static class Program
{
    internal static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    internal static JavaScriptSerializer Json { get { return new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024 }; } }
    internal static string Call(string action) { return Invoke(action, null); }
    internal static string CallAdmin(Dictionary<string, object> data) { return Invoke("admin", Json.Serialize(data)); }
    private static string Invoke(string action, string data)
    {
        string python = Path.Combine(Root, ".venv", "Scripts", "python.exe"), bridge = Path.Combine(Root, "launcher", "control.py");
        if (!File.Exists(python) || !File.Exists(bridge)) throw new IOException("请将 ZhBot.exe 保留在完整项目根目录，安装步骤见 README");
        var info = new ProcessStartInfo(python, "\"" + bridge + "\" " + action);
        info.WorkingDirectory = Root; info.UseShellExecute = false; info.CreateNoWindow = true;
        info.RedirectStandardOutput = info.RedirectStandardError = true; info.RedirectStandardInput = data != null;
        info.StandardOutputEncoding = info.StandardErrorEncoding = Encoding.UTF8; info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        var output = new StringBuilder(); var errors = new StringBuilder();
        using (var process = new Process())
        {
            process.StartInfo = info;
            process.OutputDataReceived += delegate(object s, DataReceivedEventArgs e) { if (e.Data != null) lock(output) output.AppendLine(e.Data); };
            process.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e) { if (e.Data != null) lock(errors) errors.AppendLine(e.Data); };
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            if (data != null)
            {
                byte[] bytes = new UTF8Encoding(false).GetBytes(data);
                process.StandardInput.BaseStream.Write(bytes, 0, bytes.Length); process.StandardInput.Close();
            }
            if (!process.WaitForExit(data == null ? 15000 : 120000))
            {
                process.Kill(); // Only this control helper, never the bot or WeChat.
                throw new IOException("本机操作超时，请刷新确认结果后再操作；机器人进程未被强制停止");
            }
            process.WaitForExit();
            if (output.Length == 0) throw new IOException(errors.Length == 0 ? "控制入口没有返回状态" : errors.ToString());
            return output.ToString();
        }
    }
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--check")
        {
            try
            {
                string result = Call("check"); Directory.CreateDirectory(Path.Combine(Root, "runtime"));
                File.WriteAllText(Path.Combine(Root, "runtime", "launcher-check.json"), result, new UTF8Encoding(false));
                return J.Text(Json.Deserialize<Dictionary<string, object>>(result), "state") == "CHECKED" ? 0 : 1;
            }
            catch (Exception error) { MessageBox.Show(error.Message, "ZhBot 入口检查失败"); return 1; }
        }
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new LauncherForm(args.Length == 1 && args[0] == "--status-only")); return 0;
    }
}
internal static class J
{
    internal static string Text(Dictionary<string, object> d, string key) { object v; return d.TryGetValue(key, out v) && v != null ? Convert.ToString(v) : ""; }
    internal static int Number(Dictionary<string, object> d, string key, int fallback) { int v; return Int32.TryParse(Text(d, key), out v) ? v : fallback; }
    internal static Dictionary<string, object> Object(Dictionary<string, object> d, string key) { object v; return d.TryGetValue(key, out v) ? v as Dictionary<string, object> : null; }
    internal static IEnumerable<Dictionary<string, object>> Items(Dictionary<string, object> d, string key)
    {
        object v; if (!d.TryGetValue(key, out v) || !(v is IEnumerable)) yield break;
        foreach (object row in (IEnumerable)v) { var item = row as Dictionary<string, object>; if (item != null) yield return item; }
    }
    internal static string[] Strings(object value)
    { var list = new List<string>(); if (value is IEnumerable && !(value is string)) foreach (object item in (IEnumerable)value) list.Add(Convert.ToString(item)); return list.ToArray(); }
    internal static Dictionary<string, object> Request(string action) { return new Dictionary<string, object> { { "action", action } }; }
}
internal sealed class Choice
{
    internal string Id, Name; internal string[] Groups = new string[0];
    internal Choice(string id, string name) { Id = id; Name = name; }
    public override string ToString() { return Name == Id || Id == "" ? Name : Name + "  [" + Id + "]"; }
}
internal static class Ui
{
    internal static Button Button(string text, EventHandler handler)
    {
        var b = new Button { Text = text, AutoSize = true, MinimumSize = new Size(92, 32), Padding = new Padding(8, 2, 8, 2), Margin = new Padding(0, 0, 10, 0) };
        if (handler != null) b.Click += handler; return b;
    }
    internal static Label Label(string text) { return new Label { Text = text, AutoSize = true, Margin = new Padding(0, 8, 12, 0) }; }
    internal static FlowLayoutPanel Bar() { return new FlowLayoutPanel { Dock = DockStyle.Top, Height = 46, WrapContents = false, Padding = new Padding(0, 6, 0, 4) }; }
    internal static string Id(ComboBox box) { var c = box.SelectedItem as Choice; return c == null ? "" : c.Id; }
    internal static string[] Words(string text) { return text.Split(new char[] { ' ', '\r', '\n', '\t', ',', '，', ';', '；' }, StringSplitOptions.RemoveEmptyEntries); }
}
internal sealed class ListPane : UserControl
{
    internal readonly DataGridView Grid = new DataGridView(); internal readonly FlowLayoutPanel Tools = Ui.Bar();
    internal int Page = 1, Pages = 1; internal Action Reload;
    private readonly Label pageLabel = Ui.Label("尚未读取"); private readonly Button previous, next; private readonly string[] fields;
    internal ListPane(string[] fields, string[] titles)
    {
        this.fields = fields; Dock = DockStyle.Fill;
        Grid.Dock = DockStyle.Fill; Grid.ReadOnly = true; Grid.AllowUserToAddRows = Grid.AllowUserToDeleteRows = false;
        Grid.RowHeadersVisible = false; Grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        Grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill; Grid.BackgroundColor = Color.White;
        Grid.RowTemplate.Height = 32; Grid.ColumnHeadersHeight = 38; Grid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        Grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(246, 249, 252); Grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(48, 91, 135);
        for (int i = 0; i < fields.Length; i++)
        {
            int index = Grid.Columns.Add(fields[i], titles[i]);
            Grid.Columns[index].MinimumWidth = fields[i] == "member_id" || fields[i] == "group_id" ? 160 : fields[i] == "date" ? 145 : fields[i] == "member" || fields[i] == "word" ? 110 : fields[i] == "result" ? 150 : 66;
        }
        var paging = Ui.Bar(); paging.Dock = DockStyle.Bottom; paging.Height = 44;
        previous = Ui.Button("上一页", delegate { if (Page > 1) { Page--; if (Reload != null) Reload(); } });
        next = Ui.Button("下一页", delegate { if (Page < Pages) { Page++; if (Reload != null) Reload(); } });
        paging.Controls.AddRange(new Control[] { previous, next, pageLabel }); Controls.Add(Grid); Controls.Add(paging); Controls.Add(Tools);
    }
    internal Dictionary<string, object> Selected() { return Grid.CurrentRow == null ? null : Grid.CurrentRow.Tag as Dictionary<string, object>; }
    internal void Fill(Dictionary<string, object> result)
    {
        Grid.Rows.Clear();
        foreach (var item in J.Items(result, "items"))
        { object[] values = new object[fields.Length]; for (int i = 0; i < fields.Length; i++) values[i] = J.Text(item, fields[i]); Grid.Rows[Grid.Rows.Add(values)].Tag = item; }
        Page = J.Number(result, "page", Page); Pages = Math.Max(1, J.Number(result, "pages", 1));
        pageLabel.Text = "第 " + Page + " / " + Pages + " 页    共 " + J.Number(result, "total", 0) + " 条"; previous.Enabled = Page > 1; next.Enabled = Page < Pages;
    }
}
internal sealed class LauncherForm : Form
{
    private readonly Label headline = new Label(), summary = new Label(), footer = new Label();
    private readonly TextBox details = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical, BackColor = Color.White };
    private readonly Button start, stop;
    private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    private readonly TabControl tabs = new TabControl();
    private readonly ComboBox groups = new ComboBox(), members = new ComboBox();
    private readonly List<Choice> knownGroups = new List<Choice>(), knownMembers = new List<Choice>();
    private readonly ListPane zxj, wins, stickers;
    private readonly PictureBox preview = new PictureBox();
    private readonly Label previewInfo = new Label();
    private readonly CheckBox showOriginal = new CheckBox();
    private MemoryStream previewStream;
    private bool controlBusy, adminBusy, populating;
    private string startupLog = "", ownerId = "";
    internal LauncherForm(bool statusOnly)
    {
        Text = "ZhBot · 机器人管理"; Font = new Font("Microsoft YaHei UI", 10);
        AutoScaleMode = AutoScaleMode.Dpi; ClientSize = new Size(1080, 720); MinimumSize = new Size(900, 600);
        StartPosition = FormStartPosition.CenterScreen; BackColor = Color.FromArgb(245, 247, 250);
        var shell = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20, 12, 20, 10), ColumnCount = 1, RowCount = 5 };
        shell.RowStyles.Add(new RowStyle(SizeType.Absolute, 46)); shell.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));
        shell.RowStyles.Add(new RowStyle(SizeType.Absolute, 48)); shell.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); shell.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        headline.Text = "正在检查机器人状态…"; headline.Font = new Font(Font.FontFamily, 18, FontStyle.Bold); headline.Dock = DockStyle.Fill; headline.TextAlign = ContentAlignment.MiddleLeft;
        start = Ui.Button("启动机器人", delegate { ExecuteControl("start"); });
        stop = Ui.Button("正常停止", delegate { ExecuteControl("stop"); });
        var controls = Ui.Bar(); controls.Controls.AddRange(new Control[] { start, stop, Ui.Button("刷新数据", delegate { LoadOverview(true); ExecuteControl("status"); }), Ui.Label("关闭管理窗口后，机器人继续后台运行") });
        var filters = Ui.Bar(); groups.Width = 330; members.Width = 330;
        groups.DropDownStyle = members.DropDownStyle = ComboBoxStyle.DropDownList; groups.DropDownWidth = members.DropDownWidth = 550;
        filters.Controls.AddRange(new Control[] { Ui.Label("群"), groups, Ui.Label("成员"), members });
        groups.SelectedIndexChanged += delegate { if (!populating) { PopulateMembers(""); ResetLists(); } };
        members.SelectedIndexChanged += delegate { if (!populating) ResetLists(); };
        tabs.Dock = DockStyle.Fill; tabs.Padding = new Point(22, 7);
        var overview = Page("运行概览"); summary.Dock = DockStyle.Top; summary.Height = 80; summary.Font = new Font(Font.FontFamily, 12); summary.Padding = new Padding(10); summary.BackColor = Color.FromArgb(232, 241, 250);
        overview.Controls.Add(details); overview.Controls.Add(summary);
        zxj = new ListPane(new[] { "date", "member", "member_id", "result" }, new[] { "日期", "成员", "微信 ID", "收集的 zxj" });
        zxj.Tools.Controls.Add(Ui.Button("编辑 z / x / j 字库", delegate { EditCharacters(); })); zxj.Tools.Controls.Add(Ui.Label("按群筛选成员的全局历史 · 当天结果保留"));
        zxj.Reload = delegate { LoadHistory("zxj_history", zxj); }; Page("zxj 记录").Controls.Add(zxj);
        wins = new ListPane(new[] { "date", "member", "member_id", "word", "length", "guesses", "group_id" }, new[] { "猜中时间", "成员", "微信 ID", "猜中的单词", "长度", "猜测次数", "群 ID" });
        wins.Tools.Controls.Add(Ui.Button("管理 Wordle 词库", delegate { using (var dialog = new WordsDialog(this)) dialog.ShowDialog(this); })); wins.Tools.Controls.Add(Ui.Label("仅展示已猜中的对局"));
        wins.Reload = delegate { LoadHistory("wordle_wins", wins); }; Page("Wordle 战绩").Controls.Add(wins);
        stickers = new ListPane(new[] { "id", "member", "member_id", "date", "source_format", "frames", "origin" }, new[] { "编号", "上传者", "微信 ID", "添加时间", "原件格式", "帧数", "来源" });
        stickers.Tools.Controls.Add(Ui.Button("从本机添加", delegate { AddSticker(); })); stickers.Tools.Controls.Add(Ui.Button("删除选中表情", delegate { DeleteSticker(); })); stickers.Tools.Controls.Add(Ui.Label("同群成员共用表情池"));
        stickers.Grid.MultiSelect = false; stickers.Reload = delegate { LoadHistory("stickers", stickers); }; stickers.Grid.SelectionChanged += delegate { PreviewSticker(); };
        var media = new SplitContainer { Dock = DockStyle.Fill, FixedPanel = FixedPanel.Panel2, SplitterWidth = 8 };
        media.Panel1.Controls.Add(stickers); media.Panel2.Padding = new Padding(8);
        preview.Dock = DockStyle.Fill; preview.SizeMode = PictureBoxSizeMode.Zoom; preview.BackColor = Color.FromArgb(236, 239, 243);
        previewInfo.Dock = DockStyle.Bottom; previewInfo.Height = 112; previewInfo.Padding = new Padding(0, 10, 0, 0);
        showOriginal.Text = "预览原件"; showOriginal.Dock = DockStyle.Top; showOriginal.Height = 34; showOriginal.CheckedChanged += delegate { PreviewSticker(); };
        media.Panel2.Controls.Add(preview); media.Panel2.Controls.Add(previewInfo); media.Panel2.Controls.Add(showOriginal); Page("表情库").Controls.Add(media);
        media.SizeChanged += delegate { if (media.Width > 600) media.SplitterDistance = media.Width - 300; };
        tabs.SelectedIndexChanged += delegate { RefreshSelected(); };
        footer.Dock = DockStyle.Fill; footer.TextAlign = ContentAlignment.MiddleLeft; footer.ForeColor = Color.FromArgb(75, 89, 105); footer.Text = "本机管理 · 使用当前项目的运行数据库";
        shell.Controls.Add(headline, 0, 0); shell.Controls.Add(controls, 0, 1); shell.Controls.Add(filters, 0, 2); shell.Controls.Add(tabs, 0, 3); shell.Controls.Add(footer, 0, 4); Controls.Add(shell);
        timer.Interval = 4000; timer.Tick += delegate { ExecuteControl("status"); };
        Shown += delegate { ExecuteControl(statusOnly ? "status" : "start"); LoadOverview(false); timer.Start(); };
        FormClosed += delegate { timer.Stop(); timer.Dispose(); ClearPreview(); };
    }
    private TabPage Page(string title) { var p = new TabPage(title) { Padding = new Padding(12), BackColor = Color.White }; tabs.TabPages.Add(p); return p; }
    private void ResetLists() { zxj.Page = wins.Page = stickers.Page = 1; RefreshSelected(); }
    private void RefreshSelected()
    { if (tabs.SelectedIndex == 1) zxj.Reload(); else if (tabs.SelectedIndex == 2) wins.Reload(); else if (tabs.SelectedIndex == 3) stickers.Reload(); }
    private void PopulateMembers(string selected)
    {
        populating = true; members.Items.Clear(); members.Items.Add(new Choice("", "全部成员")); string group = Ui.Id(groups);
        foreach (var member in knownMembers) if (group == "" || Array.IndexOf(member.Groups, group) >= 0) members.Items.Add(member);
        members.SelectedIndex = 0; for (int i = 0; i < members.Items.Count; i++) if (((Choice)members.Items[i]).Id == selected) members.SelectedIndex = i;
        populating = false;
    }
    private void LoadOverview(bool refreshSelection)
    {
        RunAdmin(J.Request("overview"), delegate(Dictionary<string, object> record)
        {
            string groupId = Ui.Id(groups), memberId = Ui.Id(members); ownerId = J.Text(record, "owner_id"); if (ownerId == "") ownerId = J.Text(record, "account_id");
            knownGroups.Clear(); knownMembers.Clear();
            foreach (var row in J.Items(record, "groups")) knownGroups.Add(new Choice(J.Text(row, "id"), J.Text(row, "name") == "" ? J.Text(row, "id") : J.Text(row, "name")));
            foreach (var row in J.Items(record, "members"))
            {
                var choice = new Choice(J.Text(row, "id"), J.Text(row, "name") == "" ? J.Text(row, "id") : J.Text(row, "name"));
                object values; if (row.TryGetValue("groups", out values)) choice.Groups = J.Strings(values); knownMembers.Add(choice);
            }
            populating = true; groups.Items.Clear(); groups.Items.Add(new Choice("", "全部允许群")); foreach (var choice in knownGroups) groups.Items.Add(choice); groups.SelectedIndex = 0;
            for (int i = 0; i < groups.Items.Count; i++) if (((Choice)groups.Items[i]).Id == groupId) groups.SelectedIndex = i;
            populating = false; PopulateMembers(memberId);
            var counts = J.Object(record, "counts") ?? new Dictionary<string, object>();
            summary.Text = "zxj 记录  " + J.Text(counts, "draws") + "      猜中对局  " + J.Text(counts, "wins") + "      库内表情  " + J.Text(counts, "stickers") + "\r\n机器人：" + J.Text(record, "account_id") + "    群功能：" + (J.Text(record, "paused") == "True" ? "已暂停" : "启用");
            if (refreshSelection) RefreshSelected();
        });
    }
    private void LoadHistory(string action, ListPane pane)
    {
        var request = J.Request(action); request["group_id"] = Ui.Id(groups); request["user_id"] = Ui.Id(members); request["page"] = pane.Page;
        RunAdmin(request, delegate(Dictionary<string, object> result) { pane.Fill(result); if (pane == stickers) PreviewSticker(); });
    }
    internal void RunAdmin(Dictionary<string, object> request, Action<Dictionary<string, object>> completed)
    {
        if (adminBusy) { footer.Text = "已有管理操作进行中，请等待完成后再操作"; return; }
        adminBusy = true; groups.Enabled = members.Enabled = tabs.Enabled = false;
        footer.Text = "正在读取或保存…"; var worker = new BackgroundWorker();
        worker.DoWork += delegate(object sender, DoWorkEventArgs e) { e.Result = Program.CallAdmin(request); };
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e)
        {
            worker.Dispose(); if (IsDisposed) return; adminBusy = false;
            groups.Enabled = members.Enabled = tabs.Enabled = true;
            try
            {
                if (e.Error != null) throw e.Error;
                var result = Program.Json.Deserialize<Dictionary<string, object>>((string)e.Result);
                if (J.Text(result, "ok") != "True") throw new IOException(J.Text(result, "error") == "" ? "管理请求未成功" : J.Text(result, "error"));
                footer.Text = "已更新  " + DateTime.Now.ToString("HH:mm:ss") + "  · 数据仅保存在本机项目中"; if (completed != null) completed(result);
            }
            catch (Exception error) { footer.Text = "操作未完成：" + error.Message; MessageBox.Show(this, error.Message, "管理操作未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
        }; worker.RunWorkerAsync();
    }
    private void ExecuteControl(string action)
    {
        if (controlBusy || IsDisposed) return; controlBusy = true; if (action != "status") start.Enabled = stop.Enabled = false;
        var worker = new BackgroundWorker(); worker.DoWork += delegate(object sender, DoWorkEventArgs e) { e.Result = Program.Call(action); };
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e)
        {
            worker.Dispose(); if (IsDisposed) return; controlBusy = false;
            try
            {
                if (e.Error != null) throw e.Error;
                var record = Program.Json.Deserialize<Dictionary<string, object>>((string)e.Result); string state = J.Text(record, "state");
                var meanings = new Dictionary<string, string> { { "READY", "机器人运行中" }, { "STARTING", "正在启动…" }, { "STOPPED", "机器人已停止" }, { "STOP_REQUESTED", "正在正常停止…" }, { "LOGIN_REQUIRED", "请登录绑定的机器人微信" }, { "RECONNECTING", "正在重新连接" }, { "STALE", "状态待核验" } };
                headline.Text = (meanings.ContainsKey(state) ? meanings[state] : "需要检查运行状态") + "   ·   v" + J.Text(record, "version");
                headline.ForeColor = state == "READY" ? Color.FromArgb(35, 104, 77) : Color.FromArgb(42, 55, 72);
                if (J.Text(record, "stderr_log") != "") startupLog = J.Text(record, "stderr_log");
                var lines = new StringBuilder(); lines.AppendLine("状态：" + state);
                if (J.Text(record, "pid") != "") lines.AppendLine("机器人进程：" + J.Text(record, "pid"));
                foreach (string key in new[] { "reason", "error", "launcher_note" }) if (J.Text(record, key) != "") lines.AppendLine(J.Text(record, key));
                if (state == "STOPPED" && J.Text(record, "recorded_state") != "") lines.AppendLine("退出时状态：" + J.Text(record, "recorded_state"));
                object counts; if (record.TryGetValue("counts", out counts)) lines.AppendLine("消息队列：" + Program.Json.Serialize(counts));
                lines.AppendLine("数据目录：" + J.Text(record, "data_dir")); lines.AppendLine("项目目录：" + Program.Root);
                if (startupLog != "")
                {
                    lines.AppendLine("启动错误日志：" + startupLog);
                    if (state == "STOPPED" && File.Exists(startupLog))
                        using (var stream = new FileStream(startupLog, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                        using (var reader = new StreamReader(stream, Encoding.UTF8)) { char[] buffer = new char[3000]; int n = reader.Read(buffer, 0, buffer.Length); if (n > 0) lines.AppendLine(new string(buffer, 0, n)); }
                }
                details.Text = lines.ToString(); start.Enabled = J.Text(record, "process_alive") != "True" && state != "STARTING";
                stop.Enabled = state != "STOPPED" && state != "STOP_REQUESTED" && state != "ERROR";
            }
            catch (Exception error) { headline.Text = "入口状态读取失败"; details.Text = error.Message; start.Enabled = stop.Enabled = true; }
        }; worker.RunWorkerAsync();
    }
    private void EditCharacters()
    {
        RunAdmin(J.Request("zxj_dictionary"), delegate(Dictionary<string, object> result)
        { using (var dialog = new CharactersDialog(this, J.Object(result, "characters"))) dialog.ShowDialog(this); });
    }
    private void AddSticker()
    {
        if (knownGroups.Count == 0) { MessageBox.Show(this, "请先配置允许群", "添加表情"); return; }
        using (var chooser = new StickerImportDialog(knownGroups, Ui.Id(groups), ownerId))
        {
            if (chooser.ShowDialog(this) != DialogResult.OK) return;
            var request = J.Request("sticker_add"); request["group_id"] = chooser.GroupId; request["path"] = chooser.FilePath;
            RunAdmin(request, delegate(Dictionary<string, object> result)
            {
                MessageBox.Show(this, "表情编号" + J.Text(result, "id") + (J.Text(result, "duplicate") == "True" ? "：已有同一资源" : "：添加成功"), "表情库");
                stickers.Page = 1; stickers.Reload();
            });
        }
    }
    private void DeleteSticker()
    {
        var item = stickers.Selected(); if (item == null) { MessageBox.Show(this, "先选择一个表情条目", "删除表情"); return; }
        if (MessageBox.Show(this, "从本群随机池删除表情编号 " + J.Text(item, "id") + "？\r\n删除后不再参与本群随机抽取", "删除表情", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        var request = J.Request("sticker_delete"); request["group_id"] = J.Text(item, "group_id"); request["id"] = J.Number(item, "id", 0);
        RunAdmin(request, delegate { stickers.Reload(); });
    }
    private void ClearPreview()
    { Image old = preview.Image; preview.Image = null; if (old != null) old.Dispose(); if (previewStream != null) { previewStream.Dispose(); previewStream = null; } }
    private void PreviewSticker()
    {
        ClearPreview(); var item = stickers.Selected();
        if (item == null) { previewInfo.Text = "选择条目查看预览\r\n同群所有成员可以抽到本群任一条表情"; return; }
        string path = J.Text(item, showOriginal.Checked ? "original_path" : "preview_path");
        previewInfo.Text = "编号 " + J.Text(item, "id") + " · " + J.Text(item, "source_format") + "\r\n发送副本 " + J.Text(item, "width") + " × " + J.Text(item, "height") + " · " + J.Text(item, "frames") + " 帧\r\n上传者：" + J.Text(item, "member") + "\r\n" + (showOriginal.Checked ? "当前显示原件" : "当前显示发送副本");
        if (path == "") { previewInfo.Text += "\r\n此条目没有保留原件"; return; }
        try
        {
            if (new FileInfo(path).Length > 20L * 1024 * 1024) throw new IOException("预览文件超过 20 MiB");
            previewStream = new MemoryStream(File.ReadAllBytes(path)); preview.Image = Image.FromStream(previewStream);
        }
        catch (Exception) { ClearPreview(); previewInfo.Text += "\r\n当前格式无法在 Windows 预览中显示"; }
    }
}
internal sealed class CharactersDialog : Form
{
    internal CharactersDialog(LauncherForm owner, Dictionary<string, object> characters)
    {
        Text = "编辑 zxj 字库"; Font = owner.Font; Size = new Size(760, 520); MinimumSize = new Size(600, 400); StartPosition = FormStartPosition.CenterParent;
        var panel = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 3, RowCount = 3 };
        for (int i = 0; i < 3; i++) panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.333f));
        panel.RowStyles.Add(new RowStyle(SizeType.Absolute, 38)); panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); panel.RowStyles.Add(new RowStyle(SizeType.Absolute, 76));
        var boxes = new Dictionary<string, TextBox>(); int column = 0;
        foreach (string initial in new[] { "z", "x", "j" })
        {
            panel.Controls.Add(Ui.Label(initial.ToUpper() + " 对应的单字"), column, 0);
            var box = new TextBox { Multiline = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical, Margin = new Padding(0, 0, 12, 0) };
            object values; if (characters != null && characters.TryGetValue(initial, out values)) box.Text = String.Join(" ", J.Strings(values));
            boxes[initial] = box; panel.Controls.Add(box, column++, 1);
        }
        var bottom = new FlowLayoutPanel { Dock = DockStyle.Fill }; var save = Ui.Button("保存字库", null);
        bottom.Controls.Add(save); bottom.Controls.Add(Ui.Label("用空格或换行分隔单字，每组至少保留一个字\r\n后续抽取使用新字库，已经抽到的结果不变"));
        panel.Controls.Add(bottom, 0, 2); panel.SetColumnSpan(bottom, 3); Controls.Add(panel);
        save.Click += delegate
        {
            var request = J.Request("zxj_save"); var data = new Dictionary<string, object>(); foreach (var entry in boxes) data[entry.Key] = entry.Value.Text; request["characters"] = data;
            owner.RunAdmin(request, delegate { if (!IsDisposed) { DialogResult = DialogResult.OK; Close(); } });
        };
    }
}
internal sealed class WordsDialog : Form
{
    private readonly LauncherForm owner; private readonly ListPane list;
    private readonly ComboBox length = new ComboBox(); private readonly TextBox search = new TextBox(), additions = new TextBox();
    internal WordsDialog(LauncherForm owner)
    {
        this.owner = owner; Text = "Wordle 词库"; Font = owner.Font; Size = new Size(880, 650); MinimumSize = new Size(700, 500); StartPosition = FormStartPosition.CenterParent;
        var shell = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), RowCount = 3, ColumnCount = 1 };
        shell.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); shell.RowStyles.Add(new RowStyle(SizeType.Absolute, 90)); shell.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));
        list = new ListPane(new[] { "word", "length", "kind" }, new[] { "单词", "字母数", "用途" });
        length.DropDownStyle = ComboBoxStyle.DropDownList; length.Width = 115; length.Items.Add("全部长度"); for (int i = 3; i <= 10; i++) length.Items.Add(i + " 字母"); length.SelectedIndex = 0; search.Width = 220;
        list.Tools.Controls.AddRange(new Control[] { length, search, Ui.Button("搜索", delegate { list.Page = 1; Reload(); }), Ui.Button("删除选中词", delegate { DeleteWords(); }) }); list.Reload = Reload;
        search.KeyDown += delegate(object s, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; list.Page = 1; Reload(); } };
        length.SelectedIndexChanged += delegate { list.Page = 1; Reload(); };
        var addPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(0, 8, 0, 4) };
        addPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); addPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        additions.Multiline = true; additions.Dock = DockStyle.Fill; additions.ScrollBars = ScrollBars.Vertical; var add = Ui.Button("添加单词", delegate { AddWords(); }); add.Dock = DockStyle.Fill;
        addPanel.Controls.Add(additions, 0, 0); addPanel.Controls.Add(add, 1, 0);
        var note = Ui.Label("添加 3～10 个英文字母的单词，用空格或换行分隔\r\n词库修改用于新对局，进行中的对局继续使用开局词库"); note.Dock = DockStyle.Fill;
        shell.Controls.Add(list, 0, 0); shell.Controls.Add(addPanel, 0, 1); shell.Controls.Add(note, 0, 2); Controls.Add(shell); Shown += delegate { Reload(); };
    }
    private void Reload()
    {
        var request = J.Request("wordle_dictionary"); request["length"] = length.SelectedIndex == 0 ? 0 : length.SelectedIndex + 2; request["search"] = search.Text; request["page"] = list.Page;
        owner.RunAdmin(request, delegate(Dictionary<string, object> result) { if (!IsDisposed) list.Fill(result); });
    }
    private void AddWords()
    {
        string[] words = Ui.Words(additions.Text); if (words.Length == 0) return;
        var request = J.Request("wordle_edit"); request["add"] = words; request["remove"] = new string[0];
        owner.RunAdmin(request, delegate { if (!IsDisposed) { additions.Clear(); list.Page = 1; Reload(); } });
    }
    private void DeleteWords()
    {
        var words = new List<string>(); foreach (DataGridViewRow row in list.Grid.SelectedRows) { var item = row.Tag as Dictionary<string, object>; if (item != null) words.Add(J.Text(item, "word")); }
        if (words.Count == 0) return;
        if (MessageBox.Show(this, "从词库删除选中的 " + words.Count + " 个单词？\r\n已有战绩及正在进行的对局保留", "删除单词", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        var request = J.Request("wordle_edit"); request["remove"] = words.ToArray(); request["add"] = new string[0]; owner.RunAdmin(request, delegate { if (!IsDisposed) Reload(); });
    }
}
internal sealed class StickerImportDialog : Form
{
    private readonly ComboBox group = new ComboBox(); private readonly TextBox file = new TextBox();
    internal string GroupId { get { return Ui.Id(group); } } internal string FilePath { get { return file.Text; } }
    internal StickerImportDialog(List<Choice> choices, string selected, string owner)
    {
        Text = "从本机添加表情"; ClientSize = new Size(680, 240); Font = new Font("Microsoft YaHei UI", 10); FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = false; StartPosition = FormStartPosition.CenterParent;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 3, RowCount = 4 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 80)); layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 105));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
        group.DropDownStyle = ComboBoxStyle.DropDownList; group.Dock = DockStyle.Fill; foreach (var choice in choices) group.Items.Add(choice); group.SelectedIndex = 0;
        for (int i = 0; i < group.Items.Count; i++) if (((Choice)group.Items[i]).Id == selected) group.SelectedIndex = i; file.Dock = DockStyle.Fill; file.ReadOnly = true;
        var browse = Ui.Button("选择文件", delegate
        {
            using (var picker = new OpenFileDialog { Title = "选择表情原件", Filter = "图片及 GIF|*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif|所有文件|*.*", CheckFileExists = true, Multiselect = false })
                if (picker.ShowDialog(this) == DialogResult.OK) file.Text = picker.FileName;
        });
        layout.Controls.Add(Ui.Label("目标群"), 0, 0); layout.Controls.Add(group, 1, 0); layout.SetColumnSpan(group, 2);
        layout.Controls.Add(Ui.Label("表情文件"), 0, 1); layout.Controls.Add(file, 1, 1); layout.Controls.Add(browse, 2, 1);
        var note = Ui.Label("本机添加归属：" + owner + "\r\n加入所选群的公共表情池，按原件摘要查重"); note.Dock = DockStyle.Fill; layout.Controls.Add(note, 0, 2); layout.SetColumnSpan(note, 3);
        layout.Controls.Add(Ui.Button("添加到群库", delegate { if (file.Text == "") { MessageBox.Show(this, "先选择文件"); return; } DialogResult = DialogResult.OK; Close(); }), 1, 3); Controls.Add(layout);
    }
}
