from pathlib import Path
from typing import  List,Tuple


#读取 文件夹 下的 *.md/*.txt 文件，返回一个列表，每个元素是一个元组，包含文件名和文件内容
def load_documents(data_dir:Path)->list[tuple[str,str]]:
    documents=[]
    for file_path in data_dir.rglob("*"):
        if file_path.suffix.lower() in {".md",".txt"} :
            try:
                with open(file_path,"r",encoding="utf-8") as f:
                    content = f.read()
                documents.append((file_path.name,content))
            except Exception as e:
                print(f"读取文件{file_path} 失败: {e}")
    return documents




    
