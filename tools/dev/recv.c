#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
/* one-shot receiver: recv <port> <outfile> */
int main(int c,char**v){int s=socket(AF_INET,SOCK_STREAM,0),o=1;setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&o,sizeof o);
struct sockaddr_in a;memset(&a,0,sizeof a);a.sin_family=AF_INET;a.sin_port=htons(atoi(v[1]));
if(bind(s,(void*)&a,sizeof a)||listen(s,1)){perror("bind");return 1;}
int k=accept(s,0,0),f=open(v[2],O_WRONLY|O_CREAT|O_TRUNC,0755);static char b[4096];long t=0;int n;
while((n=read(k,b,sizeof b))>0){write(f,b,n);t+=n;}close(f);close(k);printf("received %ld\n",t);return 0;}
