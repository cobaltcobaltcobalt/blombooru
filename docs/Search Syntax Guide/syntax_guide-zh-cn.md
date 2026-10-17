## 基础标签

- `tag1 tag2`: 查找同时包含两个标签的媒体
- `-tag1`: 排除包含该标签的媒体
- `tag*`: 通配符搜索
- `?tag`: 模糊搜索（前置一个或零个字符）

## 范围

运算符: `:`, `..`, `>=`, `>`, `<=`, `<`, `!=`

- `id:100`: 精确匹配
- `id:100..200`: 包含两端的闭区间
- `id:>=100`: 大于或等于
- `id:1,2,3`: 在列表内
- `gentags:13,16,<8,>91`
- `gentags:6,4 gentags:8,>4` (`gentags:>=4`)

注意：范围语法也可以与大多数元限定符一起使用。

## 元限定符

- `width`, `height`: 图片尺寸 (像素)
- `filesize`: 文件大小 (KB, MB, GB)
- `date`, `age`: 上传日期或相对时长
- `rating`: safe (全年龄), questionable (限制级), explicit (成人级)
- `source`: 来源 URL 或 none (无)
- `filetype`: 扩展名 (png, gif 等)
- `tagcount`, `gentags`, `chartags`...: 标签数量

## 排序

使用 `order:属性` 值:

- `id` / `id_desc`: 最新优先 (默认)
- `id_asc`: 最早优先
- `date_desc` / `date_asc`
- `filesize` / `filesize_asc`
- `width_desc` / `height_desc` / `mpixels_desc`
- `tagcount_desc` / `tagcount_asc`
- `landscape` / `portrait`: 宽高比

## 搜索示例

- `cat source:none rating:s`: 无来源的全年龄猫咪图片
- `landscape filetype:mp4 filesize:>5mb`: 高质量风景视频
- `id:1..100 order:id_asc`: 前 100 个上传项，按时间从旧到新
- `?girl? *_eyes -dog`: 搜索包含一个或多个女孩、任意眼睛颜色且没有狗的结果
- `tagcount:>20 arttags:0`: 带有许多标签但没有画师信息的作品
